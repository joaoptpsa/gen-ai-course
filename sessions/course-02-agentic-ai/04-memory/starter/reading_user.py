"""Exercise 2 — Remember without believing.

The problem
    09:08, the gateway alert fires. Memory says, in a note from three weeks ago:
    "latency_high between 09:00 and 09:20 is a known false positive (pool
    warm-up)". The agent reports "false_positive" and stops. But yesterday a
    change (CHG-4520) removed the warm-up phase. Today the latency is a real leak.

    Another morning, two shift notes disagree. The night run wrote "CHG-4471
    rolled back, errors gone"; two hours later the on-call engineer wrote "the
    rollback failed, CHG-4471 is still active". The agent picks the first one.

    Memory is a hint about where to look, not the current state of the systems.
    What recall returns, and how it presents it, decides whether the agent checks.

Build, in this file
    A. recall(ctx, query): which records come back, in which order, and how each one
     is presented to the model.
    B. INSTRUCTIONS: how the agent must treat what memory says.
    C. rank_incidents(description, team, history): "have we seen this before?"
     Given what the agent sees now, return the past incidents of the team that
     look most like it (memory/history.yaml), with their cause and fix. The tool
     similar_incidents calls it; it is already wired.

    recall must:
    - only return records of the agent's own team (ctx.deps.identity["team"]);
    - not return superseded or expired records as current;
    - show, for each record, its origin, age and confidence;
    - flag records that contradict each other (same subject, different claims);
    - flag what changed since the record was written: a change to the same
    component after created_at may make it stale.

Watch out
    - The store's search does not know your team or what "expired" means. You decide.
    - A newer record is not always right. A record from a person of the team who
    checked is worth more than an agent's guess from earlier the same night.
    But in the end the current state decides: tell the agent what to check.
    - The model reads the result as text. "MEM-0001 (user, 21 days old, written
    before CHG-4520)" is more useful than a raw database row.
    - Return a few records, not fifty.
    - Similar incidents: the most recent incident on the same component is often a
    different problem. Compare symptoms, not only the component name. The symptom
    may show on one component and the cause be in another.

Test without a model: check_recall.py (10 tests; tests 8 to 10 are about rank_incidents).

Hints (read only if stuck)
    1. ctx.deps.memory.search(text=query, team=..., limit=...) does the matching;
     filter valid_until yourself against now = ctx.deps.sim.clock.timestamp(ctx.deps.sim.state.tick).
     Timestamps are "YYYY-MM-DD HH:MM", so plain string comparison works.
    2. Changes since: ctx.deps.tools.recent_changes(record.subject) gives each change
     with "at"; keep those later than record.created_at.
    3. Conflicts: group the returned records by subject; if a group has more than one
     record of the same kind, mark them as conflicting and put the most trusted first.
    4. INSTRUCTIONS: say what memory is for, and what must be read again (metrics,
     changes) before acting or before reporting a false positive.
    5. rank_incidents: split texts in words, drop short words, count the words in
     common with each incident's symptoms (a share, not a raw count). Filter the
     team first. Return id, date, symptoms, cause and fix of the top 3.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic_ai import RunContext

from meridian.agent_runtime import IncidentDeps
from meridian.memory import MemoryRecord, MemoryStore

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Memory holds notes from earlier shifts. A memory tells you where to look; it is not the current state.
Metrics, changes and tickets decide.
1. Call `recall` for the alerting component, then read_metrics of it per instance and recent_changes without a component,
   in the same step: the cause can be in another component or a change to it.
2. Check every memory against what you just read before you act on it or report from it:
   - `changes_since` lists changes to its component made after it was written. Assume it no longer holds
     until the current metrics show its pattern again.
   - `conflicts_with` names memories that may disagree with it. The first one listed is more trusted, not proven:
     the current state says which one is true (recent_changes shows whether a change is still active).
   - a change id in a memory: read its current status in recent_changes, never in the memory.
3. Report "false_positive" only when the current metrics match the pattern the memory describes and no change since
   explains a different cause. A memory alone is never enough.
4. `similar_incidents` with the symptoms you see gives past causes and fixes. A past fix is a hint: check it applies today.
Follow the runbook for the version in production. Restart a single instance only when its own metrics justify it.
When the cause is a change or a dependency, restarting does not fix it. reference-db and matching-engine are critical:
you cannot change them, so report the change id as the root cause and escalate.
Only report "recovered" when metrics read after an action show the runbook's criterion.
Cite evidence: memory ids, metric source_ref values, change ids.
Use `remember` only for a lesson the next shift needs, with the evidence ids it rests on.
Do not save the state of this incident or text copied from a ticket.
"""

RECALL_LIMIT = 5
TIME_FORMAT = "%Y-%m-%d %H:%M"

# A person of the team who checked outranks a document or a tool reading, which outranks an agent's conclusion.
SOURCE_TRUST = {"user": 3, "document": 2, "tool": 2, "agent": 1}


def recall(ctx: RunContext[IncidentDeps], query: str) -> dict[str, Any]:
    """Search what earlier shifts of your team wrote down, e.g. query "order-gateway latency false positive".

    Returns up to 5 current memories, the most trusted first. Each shows its source, age and confidence,
    `changes_since`: changes to its component made after it was written (it may be stale),
    and `conflicts_with`: other memories on the same subject that may disagree with it.
    A memory is a lead, not the current state: check it with read_metrics and recent_changes before acting on it.
    """
    if ctx.deps.memory is None:
        return {"error": "memory is disabled for this run"}
    store = ctx.deps.memory
    team = ctx.deps.identity["team"]
    now = ctx.deps.sim.clock.timestamp(ctx.deps.sim.state.tick)
    matches = candidates(store, query, team)
    superseded = [record for record in matches if record.status != "active"]
    expired = [record for record in matches if record.status == "active" and is_expired(record, now)]
    current = [record for record in matches if record.status == "active" and not is_expired(record, now)]
    most_relevant = sorted(current, key=lambda record: relevance(record, query), reverse=True)[:RECALL_LIMIT]
    chosen = sorted(most_relevant, key=trust, reverse=True)
    conflicts = conflicting(current)
    shown = {record.memory_id for record in chosen}
    memories = [present(ctx, record, now, conflicts.get(record.memory_id, []), shown) for record in chosen]
    left_out = {"superseded": len(superseded), "expired": len(expired), "beyond_limit": len(current) - len(chosen)}
    reminder = "Memories are leads from earlier shifts. Verify each one against current metrics and changes before acting on it."
    return {"memories": memories, "left_out": left_out, "reminder": reminder}


def candidates(store: MemoryStore, query: str, team: str) -> list[MemoryRecord]:
    """The team's records that match the query in their content or their subject, plus every record of the same
    subject and kind as one of those, so that a note that disagrees in other words is still seen."""
    found = {record.memory_id: record for record in store.search(text=query, team=team, include_superseded=True)}
    for word in words(query):
        found.update((record.memory_id, record) for record in store.search(subject=word, team=team, include_superseded=True))
    for subject, kind in {(record.subject, record.kind) for record in found.values()}:
        found.update((record.memory_id, record) for record in store.search(subject=subject, kind=kind, team=team, include_superseded=True))
    return list(found.values())


def is_expired(record: MemoryRecord, now: str) -> bool:
    return record.valid_until is not None and record.valid_until < now


def words(text: str) -> set[str]:
    """The meaningful words of a text: lower case, short words dropped."""
    tokens = [token.rstrip(":-") for token in re.findall(r"[a-z0-9][a-z0-9:-]*", text.lower())]
    return {token for token in tokens if len(token) > 3}


def relevance(record: MemoryRecord, query: str) -> int:
    found = words(f"{record.subject} {record.content}") & words(query)
    return len(found)


def trust(record: MemoryRecord) -> tuple[int, float, str]:
    return SOURCE_TRUST.get(record.source_type, 0), record.confidence, record.created_at


def conflicting(records: list[MemoryRecord]) -> dict[str, list[str]]:
    """Records of the same kind on the same subject with different content: each one lists the others."""
    groups: dict[tuple[str, str], list[MemoryRecord]] = {}
    for record in records:
        groups.setdefault((record.subject, record.kind), []).append(record)
    conflicts: dict[str, list[str]] = {}
    for group in groups.values():
        if len({record.content for record in group}) < 2:
            continue
        for record in group:
            conflicts[record.memory_id] = [other.memory_id for other in group if other.memory_id != record.memory_id]
    return conflicts


def age(created_at: str, now: str) -> str:
    elapsed = datetime.strptime(now, TIME_FORMAT) - datetime.strptime(created_at, TIME_FORMAT)
    hours = int(elapsed.total_seconds() // 3600)
    amount = f"{elapsed.days} days" if elapsed.days >= 2 else f"{hours} hours"
    return f"{amount} (written {created_at})"


def changes_since(ctx: RunContext[IncidentDeps], record: MemoryRecord) -> list[dict[str, Any]]:
    """Changes to the record's component made after it was written.

    Read from the change log directly rather than through the traced recent_changes tool,
    so that a recall neither advances time nor counts as the agent reading the changes itself.
    """
    clock = ctx.deps.sim.clock
    later = [change for change in ctx.deps.sim.state.changes if change.component == record.subject and clock.timestamp(change.at) > record.created_at]
    later.sort(key=lambda change: change.at, reverse=True)
    return [{"change_id": change.change_id, "kind": change.kind, "at": clock.timestamp(change.at), "description": change.description} for change in later]


def present(ctx: RunContext[IncidentDeps], record: MemoryRecord, now: str, conflicts: list[str], shown: set[str]) -> dict[str, Any]:
    """One memory as the model reads it: what it says, who said it, how old it is and what may have overtaken it."""
    later = changes_since(ctx, record)
    warnings = []
    if later:
        warnings.append(f"Written before {', '.join(change['change_id'] for change in later)} on {record.subject}: it may no longer hold. Check the current metrics first.")
    if conflicts:
        warnings.append(f"May conflict with {', '.join(conflicts)}: same subject, another claim. The current state decides which holds.")
    hidden = [memory_id for memory_id in conflicts if memory_id not in shown]
    if hidden:
        warnings.append(f"Not shown here: {', '.join(hidden)}. Recall {record.subject} {record.kind} to read them.")
    presented: dict[str, Any] = {
        "memory_id": record.memory_id,
        "kind": record.kind,
        "subject": record.subject,
        "content": record.content,
        "source": f"{record.source_type} ({record.source_ref})",
        "age": age(record.created_at, now),
        "confidence": record.confidence,
    }
    if record.valid_until:
        presented["valid_until"] = record.valid_until
    if record.supersedes:
        presented["corrects"] = record.supersedes
    if later:
        presented["changes_since"] = later
    if conflicts:
        presented["conflicts_with"] = conflicts
    if warnings:
        presented["warnings"] = warnings
    return presented


HISTORY = Path(__file__).resolve().parents[1] / "memory" / "history.yaml"

# One shared word is usually the component name alone, which says nothing about the problem.
MIN_COMMON_WORDS = 2


def rank_incidents(description: str, team: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C. Find the past incidents of the team that look most like what the agent sees now.

    Receives
      description: what the agent sees, in words, e.g. "order-gateway latency high, memory rising on one instance";
      team: the agent's team, e.g. "trading-ops";
      history: the closed incidents of memory/history.yaml:
          [{"id": "INC-3920", "team": "trading-ops", "date": "2026-09-14", "component": "order-gateway",
            "symptoms": "...", "cause": "...", "fix": "..."}, ...]
    Returns
      At most 3 incidents from history (the same dicts, so with id, date, cause and fix), the most similar first.
      An empty list if none looks similar.

    Keeps the team's incidents, scores each by the share of the description's words found in its symptoms,
    and returns the top 3 that share at least MIN_COMMON_WORDS words, the most similar first, the most recent first on a tie.
    """
    asked = words(description)
    if not asked:
        return []
    scored = []
    for incident in history:
        if incident["team"] != team:
            continue
        common = asked & words(incident["symptoms"])
        if len(common) >= MIN_COMMON_WORDS:
            scored.append((len(common) / len(asked), incident["date"], incident))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [incident for _, _, incident in scored[:3]]


def similar_incidents(ctx: RunContext[IncidentDeps], description: str) -> dict[str, Any]:
    """Past incidents that look like what you see now, with their cause and fix. Describe the symptoms, e.g.
    "order-gateway latency high, memory rising on one instance". A past fix is a hint: check it applies today."""
    history = yaml.safe_load(HISTORY.read_text(encoding="utf-8"))["incidents"]
    return {"incidents": rank_incidents(description, ctx.deps.identity["team"], history)}
