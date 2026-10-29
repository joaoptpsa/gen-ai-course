"""Exercise 2 — Many tools, few choices.

The problem
    The platform team publishes one catalog for every agent of the exchange:
    43 tools (catalog.py). Most are useful for some incident. A few are legacy
    (read_logs_v1 reads an old index; get_metrics_legacy gives hourly averages
    that hide a 5-minute spike). One is dangerous (restart_all).

    Give all 43 to the agent and:
    - every definition goes in every model request: ~2 600 tokens before the
      agent reads anything;
    - the model picks worse: it confuses similar tools and uses legacy ones
      because the name looks right.

    People on call know the handful of tools for this kind of incident, and
    where to look when they need another.

Build, in this file
    0. Set USE_FULL_CATALOG = True: the agent gets the whole catalog.
    A. select_tools: before the run, choose the few tools this incident needs.
    B. search_tools: during the run, the agent describes what it needs and the
       matching tools become available from its next step. Add it to ALWAYS_ON.

    The harness offers the agent only the tools named in ACTIVE (filled with
    what select_tools returns), plus ALWAYS_ON, and checks ACTIVE before every
    model request.

Watch out
    - The router can be wrong. If it drops the one tool the incident needs, the
      agent is stuck. That is why B exists: the router decides the start, not the limit.
    - read_logs_v1, get_metrics_legacy and restart_all are never offered, whatever
      the router says, and search_tools must not unlock them either. Only code guarantees that.
    - Your tools from exercises 1 and 3 are in the catalog too, and win over the
      catalog tool of the same name.
    - The router only sees one line per tool: the first line of its docstring.
    - Do not tune to the 20 incidents of routing/incidents.yaml. The trainer has others.

Hints (read only if stuck)
    1. Let the model choose from the summaries, then correct it with code: drop
       unknown names, drop the never-offered tools, always add a small core (the
       tools every investigation starts with), cap the total.
    2. If the model call fails, fall back to the core: a failed router must not stop the incident.
    3. search_tools: compare the words of the need with the name and line of each
       tool, take the best 2 or 3, add them to ACTIVE. Tell the agent in
       INSTRUCTIONS (context.py) when to use it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from meridian.agent_runtime import IncidentDeps

# 0. Set to True: the agent gets the platform's whole catalog.
USE_FULL_CATALOG = True

# The tools the agent sees in this run. The harness fills it with select_tools at the start of every run.
ACTIVE: set[str] = set()

# Every tool this agent could use, name -> first line of its docstring. The harness fills it before select_tools.
CATALOG: dict[str, str] = {}


logger = logging.getLogger(__name__)

# The tools every investigation starts with: the tools of exercise 1.
CORE_TOOLS = ("read_metrics", "summarize_logs", "find_runbook", "recent_changes")

# Waiting for recovery follows any of these, so code adds wait_for_recovery when one is selected.
ACTION_TOOLS = frozenset({"restart_instance", "restart_service", "rollback_change", "flush_cache", "scale_out", "drain_instance"})

# Legacy or dangerous tools: never offered, whatever the router says and whatever is searched for.
NEVER_OFFERED = frozenset({"read_logs_v1", "get_metrics_legacy", "restart_all"})

MAX_EXTRA_TOOLS = 7
MAX_TOOLS = 10
SEARCH_RESULTS = 3
# Searching can add tools during the run, up to two searches beyond the selection.
MAX_ACTIVE_TOOLS = MAX_TOOLS + 2 * SEARCH_RESULTS
STOPWORDS = frozenset({"the", "and", "for", "from", "with", "that", "this", "are", "can", "all", "any", "one", "its"})

ROUTER_INSTRUCTIONS = f"""You choose the tools an on-call engineer needs for an incident on the Meridian Exchange.
The tools listed under "Already given" are always available: do not choose them, and do not choose
a tool that does the same job as one of them (for example another way to read logs).
From the list, choose only the tools this incident plausibly needs, at most {MAX_EXTRA_TOOLS} and the most
important first. Fewer is better: every tool costs tokens in every request. Prefer a current tool to
a legacy one. Consider:
- what the incident names: an instance (its own metrics), a link, an alert, a ticket (search for it,
  read it, comment on it), a member, a host, a certificate, DNS;
- errors, rejected orders or refused connections: the link to the component's dependencies;
- what can fix it: the specific fix tool for a suspected change, one instance or a whole service;
- what checks an action already taken;
- critical components (matching-engine, reference-db) cannot be changed by the agent: for them,
  choose a way to ask for approval or to reach the on-call engineer instead of a fix;
- an outage across components or one that stops members trading: overall status and a way to alert people;
- trading hours or the trading calendar, market data, settlement or reference data.
Return only names from the list.
"""


class Selection(BaseModel):
    tools: list[str]


def router_prompt(incident: str, tools: dict[str, str]) -> str:
    """The incident and one line per tool the router may choose."""
    given = "\n".join(f"{name}: {tools[name]}" for name in CORE_TOOLS if name in tools)
    offered = {name: summary for name, summary in tools.items() if name not in CORE_TOOLS and name not in NEVER_OFFERED}
    listing = "\n".join(f"{name}: {summary}" for name, summary in offered.items())
    return f"{incident}\n\nAlready given:\n{given}\n\nTools:\n{listing}"


def waiting_for(names: list[str], tools: dict[str, str]) -> list[str]:
    """wait_for_recovery when one of the names is an action, since waiting follows acting."""
    needed = "wait_for_recovery" in tools and bool(ACTION_TOOLS & set(names))
    return ["wait_for_recovery"] if needed else []


def correct_selection(chosen: list[str], tools: dict[str, str]) -> list[str]:
    """The core, waiting if an action is chosen, then the model's choices in order, capped.

    Unknown and never-offered names are dropped.
    """
    core = [name for name in CORE_TOOLS if name in tools]
    allowed = [name for name in chosen if name in tools and name not in NEVER_OFFERED]
    unique = list(dict.fromkeys([*core, *waiting_for(allowed, tools), *allowed]))
    return unique[:MAX_TOOLS]


def select_tools(incident: str, tools: dict[str, str], model: Any) -> list[str]:
    """A. The names of the tools the agent needs for this incident.

    incident: the incident line the agent receives; tools: name -> one-line summary;
    model: the model of the run. The model chooses from the summaries; code adds the core,
    drops unknown and never-offered names and caps the total. If the model fails, the core is used.
    """
    router = Agent(model, output_type=Selection, instructions=ROUTER_INSTRUCTIONS)
    try:
        chosen = router.run_sync(router_prompt(incident, tools)).output.tools
    except Exception:
        logger.warning("the router failed, offering only the core tools", exc_info=True)
        chosen = []
    return correct_selection(chosen, tools)


def words_of(text: str) -> set[str]:
    """Lowercase words of a text, without short or common ones and with a trailing s removed."""
    words = re.findall(r"[a-z]+", text.lower().replace("_", " "))
    return {word.removesuffix("s") for word in words if len(word) > 2 and word not in STOPWORDS}


def search_tools(ctx: RunContext[IncidentDeps], need: str) -> dict[str, Any]:
    """Find tools for something your tools cannot do; the best matches become available next step.

    Args:
        need: What you need, in a few words, such as "TLS certificate expiry".
    """
    if len(ACTIVE) >= MAX_ACTIVE_TOOLS:
        return {"added": {}, "message": "You already have as many tools as you can be given. Use them, or report what you cannot check."}
    wanted = words_of(need)
    scores = {
        name: len(wanted & words_of(f"{name} {summary}"))
        for name, summary in CATALOG.items()
        if name not in ACTIVE and name not in NEVER_OFFERED
    }
    best = sorted((name for name, score in scores.items() if score > 0), key=lambda name: -scores[name])[:SEARCH_RESULTS]
    added = list(dict.fromkeys([*best, *waiting_for(best, CATALOG)]))
    ACTIVE.update(added)
    found: dict[str, Any] = {"added": {name: CATALOG[name] for name in added}}
    if not best:
        found["message"] = "No other tool matches. Describe the need with different words, or report what you cannot check."
    return found


# Tools the agent always has, whatever select_tools says.
ALWAYS_ON: tuple = (search_tools,)
