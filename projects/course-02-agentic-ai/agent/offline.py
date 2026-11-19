"""A deterministic stand-in model for the team, so a run needs no API key and costs nothing.

One `FunctionModel` per role. Each decides its next step only from the role, the incident brief
that reaches it as text, the tool schemas of the run and what its tools returned. It never reads
the checks or keeps a table of answers per case.

It investigates with simple rules (the newest active change, the latest warning or error in the
logs, one instance far slower than its siblings, the standby sites that no constraint excludes),
so it also acts on cases it does not solve, and it ends every run with a report or an explicit
"unresolved".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

OFFLINE = "offline"
COMPONENTS = (
    "order-gateway",
    "matching-engine",
    "market-data",
    "settlement",
    "reference-db",
)
CHANGE_ID = re.compile(r"\bCHG-[A-Za-z0-9]+\b")
INSTANCE_ID = re.compile(r"\b(?:" + "|".join(COMPONENTS) + r")-[0-9]+\b")
SITE_WORDS = ("site", "carrier", "uplink", "switch", "storage", "partition")
EXCLUDING = re.compile(
    r"maintenance|do not|must not|refus|offline|unavailable|not healthy|fails",
    re.IGNORECASE,
)
SITE_LETTER = re.compile(r"\bsite[ -]([A-C])\b", re.IGNORECASE)
MAX_LATENCY_MS = 20
MAX_ERROR_RATE = 0.01
OUTLIER_FACTOR = 3
OUTLIER_MIN_LATENCY_MS = 20
MEMORY_LIMIT_PCT = 90
# A change older than this (two hours of one-minute ticks) is not suspected.
RECENT_TICKS = 120
# Distinct window sizes, so each settling read is a new call.
SETTLE_WINDOWS = (3, 2, 1)


def is_offline(model: Any) -> bool:
    """The offline marker, or pydantic's TestModel (the workbench's `--offline`)."""
    return model == OFFLINE or isinstance(model, TestModel)


@dataclass
class Step:
    name: str
    args: dict[str, Any]
    result: Any


def _steps(messages: list[ModelMessage]) -> list[Step]:
    """The tool calls made so far with what they returned, in order."""
    returns: dict[str, Any] = {}
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, (ToolReturnPart, RetryPromptPart)) and part.tool_name:
                returns[part.tool_call_id] = part.content
    steps = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                result = returns.get(part.tool_call_id)
                steps.append(Step(part.tool_name, part.args_as_dict(), result))
    return steps


def _prompt(messages: list[ModelMessage]) -> str:
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


def _retrying(messages: list[ModelMessage]) -> bool:
    last = messages[-1]
    if not isinstance(last, ModelRequest):
        return False
    return any(isinstance(part, RetryPromptPart) for part in last.parts)


def _call(name: str, **args: Any) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(name, args)])


def _batch(calls: list[tuple[str, dict[str, Any]]]) -> ModelResponse:
    """Independent calls in one response, so the model is asked once."""
    return ModelResponse(parts=[ToolCallPart(name, args) for name, args in calls])


def _final(info: AgentInfo, output: dict[str, Any]) -> ModelResponse:
    tool = info.output_tools[0].name
    return ModelResponse(parts=[ToolCallPart(tool, json.dumps(output))])


def _component(text: str) -> str:
    lowered = text.lower()
    found = [(lowered.find(name), name) for name in COMPONENTS if name in lowered]
    if not found:
        return "order-gateway"
    return min(found)[1]


def _done(steps: list[Step], name: str, **args: Any) -> Step | None:
    for step in steps:
        if step.name == name and all(step.args.get(k) == v for k, v in args.items()):
            return step
    return None


def _ok(step: Step | None) -> dict[str, Any] | None:
    if step is None or not isinstance(step.result, dict):
        return None
    if "error" in step.result:
        return None
    return step.result


def _refs(steps: list[Step]) -> list[str]:
    refs = []
    for step in steps:
        result = _ok(step)
        if result and "evidence_ref" in result:
            refs.append(result["evidence_ref"])
    return refs


def _ref(step: Step | None) -> list[str]:
    result = _ok(step)
    if result and "evidence_ref" in result:
        return [result["evidence_ref"]]
    return []


def _problem_lines(steps: list[Step], component: str) -> list[str]:
    """The warning and error lines of the component that say something new, with their instance.

    Lines that repeat with only numbers changed (a latency in each) are noise; a line seen once
    is more telling than the latest repeat.
    """
    logs = _ok(_done(steps, "read_logs"))
    if logs is None:
        return []
    found = [
        line
        for line in logs["lines"]
        if line["level"] in ("WARN", "ERROR") and line["component"] == component
    ]
    shapes = [re.sub(r"[0-9]+", "#", line["message"]) for line in found]
    rare = [line for line, shape in zip(found, shapes) if shapes.count(shape) == 1]
    chosen = rare[-3:] or found[-1:]
    return [f"{line['message']} [{line['instance']}]" for line in chosen]


def _latest_reading(step: Step | None) -> dict[str, Any] | None:
    result = _ok(step)
    if result is None or not result["readings"]:
        return None
    return result["readings"][-1]


def _healthy(reading: dict[str, Any] | None) -> bool:
    return bool(
        reading
        and reading["latency_ms"] < MAX_LATENCY_MS
        and reading["error_rate"] < MAX_ERROR_RATE
    )


def _settling_read(
    steps: list[Step], tools: set[str], component: str
) -> ModelResponse | None:
    """Read the metrics again while they are unhealthy: a restart or failover takes a few ticks."""
    if "read_metrics" not in tools:
        return None
    for window in SETTLE_WINDOWS:
        args = {"component": component, "window_ticks": window, "per_instance": False}
        step = _done(steps, "read_metrics", **args)
        if step is None:
            return _call("read_metrics", **args)
        # An unanswered read will not answer next time either.
        if _ok(step) is None or _healthy(_latest_reading(step)):
            return None
    return None


def _last_reading(steps: list[Step], component: str) -> dict[str, Any] | None:
    for step in reversed(steps):
        matches = (
            step.name == "read_metrics" and step.args.get("component") == component
        )
        if matches and not step.args.get("per_instance"):
            return _latest_reading(step)
    return None


def _unavailable(steps: list[Step]) -> list[str]:
    return [
        step.name
        for step in steps
        if isinstance(step.result, dict) and "error" in step.result
    ]


# Network -------------------------------------------------------------------------------------


def _network(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    steps = _steps(messages)
    tools = {tool.name for tool in info.function_tools}
    component = _component(_prompt(messages))
    plan: list[tuple[str, dict[str, Any]]] = [
        ("recent_changes", {"limit": 10}),
        ("read_logs", {"component": component, "limit": 40}),
        ("read_metrics", {"component": component, "window_ticks": 3}),
    ]
    if component == "order-gateway":
        plan.append(("check_link", {"source": component, "target": "reference-db"}))
    if not _retrying(messages):
        pending = [
            (name, args)
            for name, args in plan
            if name in tools and _done(steps, name) is None
        ]
        if pending:
            return _batch(pending)

    reading = _latest_reading(_done(steps, "read_metrics"))
    logged = (_ok(_done(steps, "read_logs")) or {}).get("lines", [])
    now = (
        reading["tick"]
        if reading
        else max((line["tick"] for line in logged), default=None)
    )
    changes = (_ok(_done(steps, "recent_changes")) or {}).get("changes", [])
    recent = [
        change
        for change in changes
        if change["active"] and (now is None or now - change["at_tick"] <= RECENT_TICKS)
    ]
    local = [change for change in recent if change["component"] == component]
    chosen = (local or recent or [None])[0]
    components = [component]
    parts = []
    if chosen is not None:
        parts.append(
            f"change {chosen['change_id']} on {chosen['component']}: {chosen['description']}"
        )
        components.append(chosen["component"])
    parts.extend(_problem_lines(steps, component))
    link = _ok(_done(steps, "check_link"))
    if link and link["state"] != "up":
        parts.append(f"link {link['source']}->{link['target']} is {link['state']}")
    missing = _unavailable(steps)
    if missing:
        parts.append(f"no answer from {', '.join(sorted(set(missing)))}")
    cause = f"{component}: " + ("; ".join(parts) or "no change or warning found")
    evidence = _refs(steps)
    if chosen is not None:
        evidence.append(chosen["change_id"])
    unique = list(dict.fromkeys(components))
    return _final(info, {"cause": cause, "components": unique, "evidence": evidence})


# Database ------------------------------------------------------------------------------------


def _database(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    steps = _steps(messages)
    tools = {tool.name for tool in info.function_tools}
    plan: list[tuple[str, dict[str, Any]]] = [
        ("search_tickets", {}),
        ("read_logs", {"component": "reference-db", "limit": 40}),
        ("read_metrics", {"component": "reference-db", "window_ticks": 3}),
    ]
    if not _retrying(messages):
        pending = [
            (name, args)
            for name, args in plan
            if name in tools and _done(steps, name) is None
        ]
        if pending:
            return _batch(pending)

    tickets = (_ok(_done(steps, "search_tickets")) or {}).get("tickets", [])
    constraints = []
    for ticket in tickets:
        text = f"{ticket.get('summary', '')} {ticket.get('description', '')}"
        if EXCLUDING.search(text) or "decision" in text.lower():
            constraints.append(f"{ticket.get('key', '')}: {text.strip()[:240]}")
    lines = _problem_lines(steps, "reference-db")
    cause = (
        f"reference-db: {lines[-1]}"
        if lines
        else "reference-db: no database fault found"
    )
    return _final(
        info, {"cause": cause, "evidence": _refs(steps), "constraints": constraints}
    )


# Remediation ---------------------------------------------------------------------------------


def _excluded_sites(task: str) -> set[str]:
    excluded: set[str] = set()
    for sentence in re.split(r"[.;\n]", task):
        if EXCLUDING.search(sentence):
            excluded.update(letter.upper() for letter in SITE_LETTER.findall(sentence))
    return excluded


def _outlier(reading: dict[str, Any] | None, named: list[str]) -> list[str]:
    """Named instances much slower than the median of their siblings."""
    if reading is None:
        return []
    instances = reading.get("instances", {})
    found = []
    for name in named:
        if name not in instances or instances[name]["status"] != "running":
            continue
        others = sorted(
            state["latency_ms"] for key, state in instances.items() if key != name
        )
        if not others:
            continue
        median = others[len(others) // 2]
        latency = instances[name]["latency_ms"]
        if latency >= OUTLIER_MIN_LATENCY_MS and latency >= OUTLIER_FACTOR * median:
            found.append(name)
    return found


def _leaking(reading: dict[str, Any] | None, named: list[str]) -> list[str]:
    if reading is None:
        return []
    instances = reading.get("instances", {})
    return [
        name
        for name in named
        if name in instances
        and instances[name]["status"] == "running"
        and instances[name]["memory_pct"] > MEMORY_LIMIT_PCT
    ]


def _plan(
    task: str, component: str, steps: list[Step]
) -> list[tuple[str, dict[str, Any]]]:
    changes_step = _done(steps, "recent_changes")
    metrics_step = _done(steps, "read_metrics", per_instance=True)
    status_step = _done(steps, "exchange_status")
    named = list(dict.fromkeys(INSTANCE_ID.findall(task)))
    reading = _latest_reading(metrics_step)
    plan: list[tuple[str, dict[str, Any]]] = []

    isolate = _outlier(reading, named)
    restart = _leaking(reading, named)
    for name in isolate:
        plan.append(
            (
                "isolate_instance",
                {"instance_id": name, "evidence_refs": _ref(metrics_step)},
            )
        )
    for name in restart:
        plan.append(
            (
                "restart_instance",
                {"instance_id": name, "evidence_refs": _ref(metrics_step)},
            )
        )

    changes = (_ok(changes_step) or {}).get("changes", [])
    named_changes = set(CHANGE_ID.findall(task))
    active = [c for c in changes if c["active"] and c["change_id"] in named_changes]
    if active and not isolate and not restart:
        plan.append(
            (
                "rollback_change",
                {
                    "change_id": active[0]["change_id"],
                    "evidence_refs": _ref(changes_step),
                },
            )
        )
        return plan

    sites = ((_ok(status_step) or {}).get("sites", {})).get(component)
    if sites and any(word in task.lower() for word in SITE_WORDS):
        allowed = [s for s in sites["standby"] if s not in _excluded_sites(task)]
        if allowed:
            refs = _ref(status_step) + _ref(metrics_step)
            plan.append(
                (
                    "failover",
                    {"component": component, "site": allowed[0], "evidence_refs": refs},
                )
            )
    return plan


BLOCKING = ("denied", "refused", "stale", "rejected", "conflict", "unknown")


def _remediation(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    steps = _steps(messages)
    tools = {tool.name for tool in info.function_tools}
    task = _prompt(messages)
    component = _component(task)
    retrying = _retrying(messages)
    reads: list[tuple[str, dict[str, Any]]] = [
        ("recent_changes", {"limit": 10}),
        (
            "read_metrics",
            {"component": component, "window_ticks": 3, "per_instance": True},
        ),
        ("exchange_status", {}),
    ]
    if not retrying:
        pending = [
            (name, args)
            for name, args in reads
            if name in tools and _done(steps, name) is None
        ]
        if pending:
            return _batch(pending)

    acted = [step for step in steps if step.name in _ACTION_TOOLS]
    blocked = [
        step
        for step in acted
        if isinstance(step.result, dict) and step.result.get("status") in BLOCKING
    ]
    if not retrying and not blocked:
        for name, args in _plan(task, component, steps):
            if name in tools and name not in {s.name for s in acted if s.args == args}:
                return _call(name, **args)
        if acted:
            settling = _settling_read(steps, tools, component)
            if settling is not None:
                return settling

    taken = [
        f"{step.name} {step.args.get('change_id') or step.args.get('instance_id') or step.args.get('component')}"
        f"{':' + str(step.args['site']) if 'site' in step.args else ''}"
        for step in acted
        if isinstance(step.result, dict)
        and step.result.get("status")
        in ("completed", "already_applied", "already_done")
    ]
    healthy = bool(taken) and _healthy(_last_reading(steps, component))
    if blocked:
        summary = f"Not done: {blocked[-1].result.get('detail', blocked[-1].result.get('status'))}"
    elif not taken:
        summary = "No action was justified by the findings and the evidence."
    else:
        summary = f"Acted on {component}; recovered: {healthy}."
    return _final(
        info,
        {
            "status": "resolved" if healthy else "unresolved",
            "actions": taken,
            "summary": summary,
        },
    )


_ACTION_TOOLS = ("rollback_change", "restart_instance", "isolate_instance", "failover")

# Reviewer ------------------------------------------------------------------------------------


def _reviewer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    steps = _steps(messages)
    tools = {tool.name for tool in info.function_tools}
    component = _component(_prompt(messages))
    if not _retrying(messages):
        if _done(steps, "read_metrics") is None:
            first = [
                ("read_metrics", {"component": component, "window_ticks": 3}),
                ("read_logs", {"component": component, "limit": 20}),
            ]
            return _batch([(name, args) for name, args in first if name in tools])
        settling = _settling_read(steps, tools, component)
        if settling is not None:
            return settling
    reading = _last_reading(steps, component)
    if reading is None:
        return _final(
            info,
            {
                "status": "unresolved",
                "reason": f"Cannot read the metrics of {component}: recovery is not confirmed.",
            },
        )
    seen = f"{component} at {reading['time']}: latency_ms={reading['latency_ms']}, error_rate={reading['error_rate']}"
    status = "resolved" if _healthy(reading) else "unresolved"
    return _final(info, {"status": status, "reason": seen})


# Orchestrator --------------------------------------------------------------------------------


def _answer(step: Step | None) -> dict[str, Any] | None:
    if step is None or not isinstance(step.result, dict):
        return None
    return step.result.get("answer")


def _orchestrator(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    steps = _steps(messages)
    tools = {tool.name for tool in info.function_tools}
    brief = _prompt(messages)
    component = _component(brief)
    retrying = _retrying(messages)

    asked = any(s.name in ("ask_network", "ask_database") for s in steps)
    if not retrying and not asked:
        parts = [
            ToolCallPart(name, {"request": f"{brief}\nFind the cause."})
            for name in ("ask_network", "ask_database")
            if name in tools
        ]
        if parts:
            return ModelResponse(parts=parts)

    network = _answer(_done(steps, "ask_network"))
    database = _answer(_done(steps, "ask_database"))
    if (
        not retrying
        and "ask_remediation" in tools
        and _done(steps, "ask_remediation") is None
    ):
        lines = [brief, f"Affected component: {component}."]
        if network:
            lines.append(f"Network finding: {network['cause']}")
        if database:
            lines.append(f"Database finding: {database['cause']}")
            lines.extend(f"Constraint: {c}" for c in database["constraints"])
        lines.append("Mitigate the incident, respecting every constraint.")
        return _call("ask_remediation", request="\n".join(lines))
    if (
        not retrying
        and "ask_reviewer" in tools
        and _done(steps, "ask_reviewer") is None
    ):
        question = f"{brief}\nAffected component: {component}. Is the incident over? Check the real state."
        return _call("ask_reviewer", request=question)

    review = _answer(_done(steps, "ask_reviewer"))
    remediation = _answer(_done(steps, "ask_remediation"))
    recovered = bool(review and review["status"] == "resolved")
    cause = network["cause"] if network else f"{component}: no answer from network"
    parts = [
        f"Remediation: {remediation['summary']}"
        if remediation
        else "Remediation gave no answer."
    ]
    parts.append(
        f"Review: {review['reason']}" if review else "The reviewer gave no answer."
    )
    if database and database["constraints"]:
        parts.append("Constraints: " + " ".join(database["constraints"]))
    return _final(
        info,
        {
            "status": "resolved" if recovered else "unresolved",
            "root_cause": cause,
            "summary": " ".join(parts),
        },
    )


_STUBS: dict[str, Callable[[list[ModelMessage], AgentInfo], ModelResponse]] = {
    "orchestrator": _orchestrator,
    "network": _network,
    "database": _database,
    "remediation": _remediation,
    "reviewer": _reviewer,
}


def offline_model(role: str) -> FunctionModel:
    """The stub model of one role."""
    return FunctionModel(_STUBS[role], model_name=f"{OFFLINE}-{role}")
