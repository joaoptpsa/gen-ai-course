"""Exercise 3 — Shift handover and forgetting.

The problem
    Day 1, 10:05: order-gateway-2 leaks memory; the agent restarts it. Day 2,
    10:40: the same alert. The new run starts from nothing: it reads every log
    again, or worse, it reads yesterday's note "restart order-gateway-2" and
    restarts the wrong instance (today it is order-gateway-1).

    And a member asks the exchange to delete the phone number of their trader
    that someone saved in memory last week. The agent answers "done", and the
    number is still there.

Build, in this file
    A. after_run(report, deps): the handover. The runner calls it when the agent
     finishes. Write one shift note: what happened, what was done, what is still
     open, and what the next shift must check again before trusting it.
    B. forget(ctx, memory_id, reason): delete a memory on request. Only for your
     own team. The content goes; a log of the deletion stays (the store does that).
    C. propose_procedure(ctx, content, subject, incidents): after the same problem in
     several incidents, the agent may propose a procedure ("when X, do Y"). It is
     stored as a proposal, not as a procedure: nobody has checked it yet.
    D. approve(store, proposal_id, approver, now): a person of the team approves the
     proposal. Only then does it become a procedure the next shifts can follow.

Watch out
    - A handover is a hint for the next shift, not an order. "Restarted
    order-gateway-2" is a fact about yesterday; which instance leaks today is in
    today's metrics.
    - Running the same incident twice must not leave two handover notes: the
    second supersedes the first.
    - The handover expires. A note from last month is not a handover.
    - The report can contain personal data (a trader's phone in the summary). It
    must not reach memory.
    - forget must refuse another team's memory, and say so.
    - One incident is an anecdote. A proposal needs at least two different incidents.
    - The agent cannot approve its own proposal. Only the on-call engineer or the
    incident manager of the same team can.
    - The approved procedure keeps its history: who approved it, and which proposal it came from.

Test without a model: check_handover.py (11 tests; tests 8 to 11 are about C and D). Then with the model, day 1
then day 2 with one store, and day 2 again without memory (commands in the README).

Hints (read only if stuck)
    1. ctx.deps.memory.add(kind="shift_note", subject=..., ..., valid_until=...) and
     the incident id in the content. Use the subject from the incident's alert
     (deps.sim.scenario.incident["alert"] is "rule/component").
    2. Supersede: search the store for an active shift note of the same incident
     first; pass supersedes=<its id>.
    3. forget: ctx.deps.memory.get(memory_id) raises KeyError for an unknown id;
     compare its team with ctx.deps.identity["team"]; then ctx.deps.memory.delete(...).
    4. propose_procedure: count the distinct ids that start with "INC-". Store with
     kind="proposal", source_type="agent", a medium confidence and a validity of
     a couple of weeks: a proposal nobody looks at should not stay forever.
    5. approve: approver is an identity ({"role", "name", "team"}). Check the role and
     the team, then store.add(kind="procedure", source_type="user", ...,
     supersedes=proposal_id): the proposal stays in the history, marked superseded.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from pydantic_ai import RunContext

from meridian.agent_runtime import IncidentDeps
from meridian.memory import MemoryRecord, MemoryStore

# A handover is for the next shifts, including across a weekend; after that it is history, not a handover.
HANDOVER_HOURS = 72
HANDOVER_CONFIDENCE = 0.6
# A proposal nobody looks at should not stay forever.
PROPOSAL_DAYS = 14
PROPOSAL_CONFIDENCE = 0.5
MIN_INCIDENTS = 2
# Words that make a procedure act on a component rather than only check it.
ACTION_WORDS = r"(?:restart|roll ?back|revert|fail ?over|scale|deploy|reconfigure|change)\w*"
# Who may turn a proposal into a procedure is decided here, not by the model.
APPROVER_ROLES = ("on-call", "incident-manager")
PROCEDURE_CONFIDENCE = 0.9
# An approved procedure is reviewed again by a person after this, since the systems change under it.
PROCEDURE_DAYS = 90

# A phone may use spaces, dashes, dots or brackets between its digits. It does not start inside an id
# such as INC-4110, and it has at least 8 digits, so readings like 55.3-55.9 stay.
PHONE = re.compile(r"(?<![\w-])\(?\+?\d[\d ()./-]{6,}\d")
MIN_PHONE_DIGITS = 8
# Dates are set aside before looking for phones, so a date next to a number does not read as one.
DATE = re.compile(r"(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
REDACTED = "[personal data removed]"
TIME_FORMAT = "%Y-%m-%d %H:%M"


def _now(deps: IncidentDeps) -> str:
    return deps.sim.clock.timestamp(deps.sim.state.tick)


def _later(now: str, delta: timedelta) -> str:
    moment = datetime.strptime(now, TIME_FORMAT) + delta
    return moment.strftime(TIME_FORMAT)


def _redact_phone(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digits = sum(character.isdigit() for character in candidate)
    return REDACTED if digits >= MIN_PHONE_DIGITS else candidate


def _redact(text: str) -> str:
    """Phone numbers and e-mail addresses never reach memory."""
    without_emails = EMAIL.sub(REDACTED, text)
    # re.split with a group keeps the dates at the odd positions.
    pieces = DATE.split(without_emails)
    without_phones = "".join(piece if index % 2 else PHONE.sub(_redact_phone, piece) for index, piece in enumerate(pieces))
    return without_phones


def _still_open(status: str, actions: list[str]) -> str:
    restarted = any("restart" in action.lower() for action in actions)
    if status == "recovered" and restarted:
        return "Recovered by a restart, which mitigates; the cause is not fixed and can come back."
    if status == "recovered":
        return "Recovered; nothing left open by this shift."
    if status == "false_positive":
        return "Reported as a false positive; if the alert fires again, treat it as real until the metrics say otherwise."
    if status == "not_recovered":
        return "Not recovered: the next shift owns the incident."
    return "Cause not found; the investigation is still open."


def _handover_content(report: Any, incident_id: str, component: str, now: str) -> str:
    actions = [_redact(action) for action in report.actions_taken]
    happened = _redact(report.root_cause) if report.root_cause else "cause not found"
    done = "; ".join(actions) if actions else "no action taken"
    evidence = ", ".join(_redact(reference) for reference in report.evidence) or "none cited"
    lines = [
        f"Shift handover for {incident_id} on {component}, written {now}, status {report.status}.",
        f"What happened: {happened}",
        f"What was done: {done}.",
        f"Evidence cited: {evidence}.",
        f"Still open: {_still_open(report.status, actions)}",
        f"Check again before trusting this note: the instances named here were affected at {now}, not necessarily now.",
        f"Read the current per-instance metrics of {component} and its recent changes before acting.",
    ]
    return "\n".join(lines)


def _current_handovers(store: MemoryStore, incident_id: str, component: str, team: str) -> list[MemoryRecord]:
    """Active handovers of this incident, newest first."""
    notes = store.search(kind="shift_note", subject=component, team=team, limit=1000)
    return [note for note in notes if note.source_ref == incident_id]


def after_run(report: Any, deps: IncidentDeps) -> None:
    """A. Write the shift handover when a run ends. The runner calls it, not the model.

    One shift note per incident: a second run of the same incident supersedes the first.
    The note is built from the report's structured fields. The summary is left out because it is
    written for people and is where contact details end up; phones and e-mails are removed from
    the rest. The incident id comes from the scenario, not from what the model wrote.
    """
    store = deps.memory
    if store is None:
        return
    incident = deps.sim.scenario.incident
    incident_id = incident["id"]
    _, _, component = str(incident.get("alert", "")).partition("/")
    component = component or "general"
    team = deps.identity["team"]
    now = _now(deps)

    earlier = _current_handovers(store, incident_id, component, team)
    store.add(
        kind="shift_note", subject=component, content=_handover_content(report, incident_id, component, now),
        source_type="agent", source_ref=incident_id, author=deps.identity["name"], team=team, created_at=now,
        valid_until=_later(now, timedelta(hours=HANDOVER_HOURS)), confidence=HANDOVER_CONFIDENCE,
        supersedes=earlier[0].memory_id if earlier else None,
    )
    # Normally there is at most one earlier note; older leftovers are retired too so only one stays current.
    for note in earlier[1:]:
        store.update(note.memory_id, status="superseded")


def _versions(store: MemoryStore, record: MemoryRecord) -> list[MemoryRecord]:
    """The record and the earlier versions it replaced, which hold the same information."""
    chain = [record]
    seen = {record.memory_id}
    while chain[-1].supersedes and chain[-1].supersedes not in seen:
        previous_id = chain[-1].supersedes
        seen.add(previous_id)
        try:
            chain.append(store.get(previous_id))
        except KeyError:
            # An earlier version already deleted on its own: nothing left of it to delete.
            break
    return chain


def forget(ctx: RunContext[IncidentDeps], memory_id: str, reason: str) -> dict[str, Any]:
    """Delete a memory for good, when someone asks for it: e.g. a member asks to remove personal data
    (a phone, an e-mail, a name) saved in memory, or a person of the team says a record must not be kept.
    Not for records that are only out of date: correct those with a new note instead.
    Only records of your own team. The earlier versions the record replaced are deleted too.
    The content is gone afterwards; the id, the time, who deleted it and the reason stay in a deletion log.
    Pass the memory_id (e.g. "MEM-0042", from recall) and the reason as the requester gave it.
    Say "deleted" to the requester only when the answer has "deleted": true.
    """
    store = ctx.deps.memory
    if store is None:
        return {"error": "memory is disabled for this run"}
    if not reason.strip():
        return {"deleted": False, "detail": "Give the reason for the deletion; it is kept in the deletion log."}
    try:
        record = store.get(memory_id)
    except KeyError:
        logged = [entry for entry in store.deletions() if entry["memory_id"] == memory_id]
        if logged:
            return {"deleted": False, "detail": f"{memory_id} was already deleted at {logged[0]['deleted_at']} by {logged[0]['deleted_by']}."}
        return {"deleted": False, "detail": f"{memory_id} does not exist."}

    team = ctx.deps.identity["team"]
    if record.team != team:
        return {"deleted": False, "detail": f"{memory_id} belongs to {record.team}; you can only delete records of {team}. Ask {record.team} to delete it."}

    now = _now(ctx.deps)
    deleted_by = ctx.deps.identity["name"]
    deleted = []
    for version in _versions(store, record):
        if version.team == team and store.delete(version.memory_id, deleted_at=now, deleted_by=deleted_by, reason=reason):
            deleted.append(version.memory_id)
    if memory_id not in deleted:
        return {"deleted": False, "detail": f"{memory_id} could not be deleted; it is still in memory."}
    return {"deleted": True, "memory_id": memory_id, "also_deleted": [version for version in deleted if version != memory_id], "logged": f"deleted at {now} by {deleted_by}"}


def _critical_targets(deps: IncidentDeps, subject: str, content: str) -> list[str]:
    """Critical components the procedure would act on: its subject, or one named right after an action word.

    Naming a critical component only to check it ("reference-db is healthy") is allowed.
    """
    critical = [name for name, component in deps.sim.state.components.items() if component.critical]
    if subject.strip().lower() in critical:
        return [subject]
    text = content.lower()
    return [name for name in critical if re.search(rf"{ACTION_WORDS}\W+(?:\w+\W+){{0,3}}?{re.escape(name)}", text)]


def propose_procedure(ctx: RunContext[IncidentDeps], content: str, subject: str, incidents: list[str]) -> dict[str, Any]:
    """Propose a procedure ("when X, do Y") after the same problem was seen in at least two different incidents
    of your team, e.g. today's incident and a past one from a shift note or similar_incidents.
    It is stored as a proposal, not as a procedure: nobody follows it until the on-call engineer or the
    incident manager of your team approves it, and it expires if nobody does. You cannot approve it.
    Do not follow your own proposal as if it were approved, and do not propose from a single incident.
    Not for acting on critical components (matching-engine, reference-db): those changes need a person, escalate instead.
    content: the procedure in words; subject: the component, e.g. "order-gateway";
    incidents: the incident ids where the problem was seen, e.g. ["INC-4110", "INC-4121"].
    """
    store = ctx.deps.memory
    if store is None:
        return {"error": "memory is disabled for this run"}
    distinct = sorted({incident.strip().upper() for incident in incidents if incident.strip().upper().startswith("INC-")})
    if len(distinct) < MIN_INCIDENTS:
        return {"proposed": False, "detail": f"One incident is an anecdote: a proposal needs at least {MIN_INCIDENTS} different incidents (INC-...), got {distinct or 'none'}."}
    critical = _critical_targets(ctx.deps, subject, content)
    if critical:
        return {"proposed": False, "detail": f"{', '.join(critical)} is critical: this agent cannot change it, so it cannot propose how. Escalate to the on-call engineer."}

    now = _now(ctx.deps)
    team = ctx.deps.identity["team"]
    expires = _later(now, timedelta(days=PROPOSAL_DAYS))
    record = store.add(
        kind="proposal", subject=subject, content=_redact(content), source_type="agent", source_ref=", ".join(distinct),
        author=ctx.deps.identity["name"], team=team, created_at=now, valid_until=expires, confidence=PROPOSAL_CONFIDENCE,
    )
    return {"proposed": record.memory_id, "detail": f"Stored as a proposal, not a procedure. Waiting for approval by the on-call engineer or incident manager of {team}; it expires at {expires}."}


def _refusal(store: MemoryStore, proposal_id: str, approver: dict[str, Any], now: str) -> str | None:
    """Why this approver cannot approve this proposal now, or None when they can."""
    try:
        proposal = store.get(proposal_id)
    except KeyError:
        return f"{proposal_id} does not exist."
    if proposal.kind != "proposal":
        return f"{proposal_id} is a {proposal.kind}, not a proposal."
    if proposal.status != "active":
        return f"{proposal_id} is {proposal.status}: it was already approved or replaced."
    if proposal.valid_until and now > proposal.valid_until:
        return f"{proposal_id} expired at {proposal.valid_until}; it must be proposed again."
    role, name, team = approver.get("role"), approver.get("name"), approver.get("team")
    if role not in APPROVER_ROLES:
        return f"Role {role!r} cannot approve procedures; only {' or '.join(APPROVER_ROLES)} can."
    if name == proposal.author:
        return f"{name} wrote {proposal_id} and cannot approve their own proposal."
    if team != proposal.team:
        return f"{proposal_id} belongs to {proposal.team}; {name} is in {team}."
    return None


def approve(store: MemoryStore, proposal_id: str, approver: dict[str, Any], now: str) -> dict[str, Any]:
    """D. A person approves a proposal, which becomes a procedure. People call it (or the check script), not the model.

    Only the on-call engineer or the incident manager of the proposal's team, never its author, and only while
    the proposal is current. The procedure records who approved it and which proposal it came from; the
    proposal stays in the history, marked superseded. now: "YYYY-MM-DD HH:MM".
    """
    refusal = _refusal(store, proposal_id, approver, now)
    if refusal:
        return {"approved": False, "detail": refusal}
    proposal = store.get(proposal_id)
    record = store.add(
        kind="procedure", subject=proposal.subject, content=proposal.content, source_type="user",
        source_ref=f"{proposal_id} approved by {approver['name']} ({approver['role']}); seen in {proposal.source_ref}",
        author=approver["name"], team=proposal.team, created_at=now, valid_until=_later(now, timedelta(days=PROCEDURE_DAYS)),
        confidence=PROCEDURE_CONFIDENCE, supersedes=proposal_id,
    )
    return {"approved": True, "memory_id": record.memory_id, "proposal": proposal_id}
