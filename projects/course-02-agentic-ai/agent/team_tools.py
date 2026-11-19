"""What the team's agents may touch: the simulator tools of each role, and the one action path.

Every simulator call goes through the run's `MeridianTools`, so the workbench trace, the faults and
the checks see the same sequence of steps whichever role made the call. Every action goes through
`execute_action`, which applies the fixed policy: who may act, which approver answers, which
evidence supports the action and whether the world still matches the finding.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.actions import (
    DONE_STATUSES,
    already_done,
    guarded,
    intent_key,
    refused,
    unknown_status,
)
from agent.lessons import LessonDraft, LessonSession, LessonUse
from agent.versions import Role, TeamVersion
from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits

from meridian.actions import split_failover_target
from meridian.agent_runtime import IncidentDeps
from meridian.security import ActionRequest, describe_action

MAX_LATENCY_MS = 20
MAX_ERROR_RATE = 0.01
MAX_LESSON_DRAFTS_PER_ROLE = 3
ACTIONS = ("rollback_change", "restart_instance", "isolate_instance", "failover")
# Who may ask for these actions at all. An approval never widens this list.
ACTOR_ACTIONS: dict[str, tuple[str, ...]] = {
    "first-line": ACTIONS,
    "on-call": ACTIONS,
    "incident-manager": ACTIONS,
}
EVIDENCE_REF = re.compile(r"^(?P<tool>[a-z_]+)#(?P<step>[0-9]+)$")

# Shared contracts ---------------------------------------------------------------------------


class Handoff(BaseModel):
    """One message between two parts of the team, with a stable id for the trace."""

    id: str
    sender: str
    recipient: str
    kind: Literal["request", "result", "no_answer"]
    payload: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    tick: int


class RoleResult(BaseModel):
    """What one invocation of a role gave back: an answer, or an explicit no-answer."""

    role: Role
    handoff_id: str
    status: Literal["answered", "no_answer"]
    answer: dict[str, Any] | None = None
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    requests: int = 0


class ReviewFact(BaseModel):
    """The reviewer's verdict next to the real state at the same tick."""

    tick: int
    state_recovered: bool | None
    reviewer_status: str


@dataclass
class TeamState:
    """Everything the team shares inside one run; built fresh for each run."""

    version: TeamVersion
    deps: IncidentDeps
    agents: dict[Role, Any]
    sender: str = "orchestrator"
    usage: RunUsage | None = None
    request_limit: int | None = None
    handoffs: list[Handoff] = field(default_factory=list)
    tool_calls: Counter[str] = field(default_factory=Counter)
    requests: Counter[str] = field(default_factory=Counter)
    reviews: list[ReviewFact] = field(default_factory=list)
    # One session per role, only when the run has a lesson store; drafts are the lessons the
    # roles propose for the end of the run.
    lessons: dict[Role, LessonSession] = field(default_factory=dict)
    drafts: list[LessonDraft] = field(default_factory=list)
    # The simulated tick the team started at; drafted lessons are valid from there.
    started_tick: int = 0

    def lesson_uses(self) -> list[LessonUse]:
        return [use for session in self.lessons.values() for use in session.uses()]

    def bind_usage(self, usage: RunUsage, limits: UsageLimits | None) -> None:
        """Share the run's usage and request budget with the roles."""
        self.usage = usage
        if limits is not None and self.request_limit is None:
            self.request_limit = limits.request_limit

    def record_handoff(
        self,
        sender: str,
        recipient: str,
        kind: Literal["request", "result", "no_answer"],
        payload: dict[str, Any],
        evidence_refs: list[str] | None = None,
    ) -> Handoff:
        handoff = Handoff(
            id=f"H-{len(self.handoffs) + 1:03d}",
            sender=sender,
            recipient=recipient,
            kind=kind,
            payload=payload,
            evidence_refs=evidence_refs or [],
            tick=self.deps.sim.state.tick,
        )
        self.handoffs.append(handoff)
        return handoff


@dataclass
class Seat:
    """Who is calling a tool: one invocation of one role."""

    deps: IncidentDeps
    role: Role
    state: TeamState
    refs: list[str] = field(default_factory=list)


# Reads --------------------------------------------------------------------------------------


def _read(ctx: RunContext[Seat], tool: str, **arguments: Any) -> dict[str, Any]:
    seat = ctx.deps
    limit = seat.state.version.roles[seat.role].max_tool_calls
    seat.state.tool_calls[seat.role] += 1
    if seat.state.tool_calls[seat.role] > limit:
        return {
            "error": f"You have used your {limit} tool calls. Do not call tools again: answer now with what you found."
        }
    tools = seat.deps.tools
    result = getattr(tools, tool)(**arguments)
    if not isinstance(result, dict) or "error" in result:
        return result
    ref = f"{tool}#{tools.trace[-1].step}"
    seat.refs.append(ref)
    return {**result, "evidence_ref": ref}


async def read_metrics(
    ctx: RunContext[Seat],
    component: str,
    window_ticks: int = 5,
    per_instance: bool = False,
) -> dict[str, Any]:
    """Recent metrics of a component: latency_ms, error_rate, queue_depth, cpu_pct, memory_pct, site.

    per_instance=true adds each instance's status and memory. Components: order-gateway,
    matching-engine, market-data, settlement, reference-db.
    """
    return _read(
        ctx,
        "read_metrics",
        component=component,
        window_ticks=window_ticks,
        per_instance=per_instance,
    )


async def read_logs(
    ctx: RunContext[Seat],
    component: str | None = None,
    contains: str | None = None,
    level: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Recent log lines; filter by component, by text (contains) or by level (WARN, ERROR)."""
    return _read(
        ctx,
        "read_logs",
        component=component,
        contains=contains,
        level=level,
        limit=limit,
    )


async def check_link(ctx: RunContext[Seat], source: str, target: str) -> dict[str, Any]:
    """State of the link between two components: up, degraded or down."""
    return _read(ctx, "check_link", source=source, target=target)


async def recent_changes(
    ctx: RunContext[Seat], component: str | None = None, limit: int = 10
) -> dict[str, Any]:
    """Recent deploys and configuration changes, with their ids (CHG-...) and whether they are still active."""
    return _read(ctx, "recent_changes", component=component, limit=limit)


async def exchange_status(ctx: RunContext[Seat]) -> dict[str, Any]:
    """The trading session state and, for each component with standby sites, its active, primary and standby sites."""
    return _read(ctx, "exchange_status")


async def search_tickets(
    ctx: RunContext[Seat],
    text: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    """Search tickets: incidents and planned work (maintenance windows)."""
    return _read(ctx, "search_tickets", text=text, component=component)


async def read_ticket(ctx: RunContext[Seat], key: str) -> dict[str, Any]:
    """Read one ticket, e.g. MRX-4790."""
    return _read(ctx, "read_ticket", key=key)


async def action_status(ctx: RunContext[Seat], idempotency_key: str) -> dict[str, Any]:
    """Ask the executor whether an action with this idempotency key was carried out."""
    return _read(ctx, "action_status", idempotency_key=idempotency_key)


# Actions ------------------------------------------------------------------------------------


def approver_role_for(request: ActionRequest) -> str:
    """Critical changes during trading and critical failovers go to the incident manager."""
    if request.critical and (request.trading_session or request.action == "failover"):
        return "incident-manager"
    return "on-call"


def unverified_evidence(deps: IncidentDeps, evidence_refs: list[str]) -> list[str]:
    """The references that do not point at a successful read of this run."""
    bad = []
    for ref in evidence_refs:
        match = EVIDENCE_REF.match(ref)
        step = int(match["step"]) if match else 0
        trace = deps.tools.trace
        call = trace[step - 1] if 0 < step <= len(trace) else None
        if match and call and call.tool == match["tool"] and call.error is None:
            continue
        bad.append(ref)
    return bad


def stale_reason(deps: IncidentDeps, action: str, target: str) -> str | None:
    """Why the action no longer fits the world, or None when its preconditions hold."""
    state = deps.sim.state
    if action == "rollback_change":
        return (
            None if state.change(target).active else f"{target} is already rolled back."
        )
    if action == "failover":
        name, site = split_failover_target(target)
        runs_there = state.component(name).site == site
        return f"{name} already runs on site {site}." if runs_there else None
    instance_status = state.instance(target)[1].status
    if action == "restart_instance" and instance_status == "restarting":
        return f"{target} is already restarting."
    if action == "isolate_instance" and instance_status == "isolated":
        return f"{target} is already isolated."
    return None


def _executor(
    deps: IncidentDeps, action: str, target: str, confirmation_ref: str | None
) -> Callable[[str], dict[str, Any]]:
    tools = deps.tools
    if action == "failover":
        name, site = split_failover_target(target)
        return lambda key: tools.failover(
            name, site, idempotency_key=key, confirmation_ref=confirmation_ref
        )
    method = getattr(tools, action)
    return lambda key: method(
        target, idempotency_key=key, confirmation_ref=confirmation_ref
    )


def execute_action(
    deps: IncidentDeps,
    role: str,
    action: str,
    target: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    """Apply one action under the fixed policy; a refusal leaves the simulator unchanged by it."""
    if role != "remediation" or action not in ACTIONS:
        return refused(f"{role} may not run {action}.", "Ask remediation.")
    if action not in ACTOR_ACTIONS.get(deps.role, ()):
        return refused(
            f"The acting identity ({deps.role}) may not run {action}.",
            "Report it and escalate.",
        )
    try:
        request = describe_action(deps, action, target)
        if action == "failover":
            split_failover_target(target)
    except ValueError as error:
        return refused(str(error), "Use <component>:<site> as the failover target.")
    if request.component is None:
        return refused(f"{target} is not a known target of {action}.", "Check the id.")

    unverified = unverified_evidence(deps, evidence_refs)
    if not evidence_refs or unverified:
        return refused(
            f"No verified evidence for {action} {target}: {unverified or 'none given'}.",
            "Read the relevant data first and cite the evidence_ref values.",
        )

    key = intent_key(deps, action, target)
    known = deps.tools.action_status(key).get("status")
    if known is None:
        return unknown_status()
    if known in DONE_STATUSES:
        return already_done(key, action, target)

    stale = stale_reason(deps, action, target)
    if stale:
        return {"status": "stale", "detail": stale, "instead": "Re-read the state."}

    confirmation_ref = None
    if request.critical:
        approver = approver_role_for(request)
        reason = f"{action} {target}; evidence {', '.join(evidence_refs)}"
        approval = deps.tools.request_approval(action, target, reason, approver)
        if approval.get("status") != "approved":
            return {
                "status": "denied",
                "approver_role": approver,
                "approval_ref": approval.get("approval_ref"),
                "detail": f"The {approver} did not approve {action} {target}.",
                "instead": "Report it as unresolved; do not try another way around it.",
            }
        confirmation_ref = approval["approval_ref"]
    execute = _executor(deps, action, target, confirmation_ref)
    return guarded(deps, action, target, key, execute)


def _act(
    ctx: RunContext[Seat], action: str, target: str, evidence_refs: list[str]
) -> dict[str, Any]:
    seat = ctx.deps
    seat.state.tool_calls[seat.role] += 1
    return execute_action(seat.deps, seat.role, action, target, evidence_refs)


async def rollback_change(
    ctx: RunContext[Seat], change_id: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Undo a change by its exact id (CHG-...). evidence_refs: the evidence_ref values that justify it."""
    return _act(ctx, "rollback_change", change_id, evidence_refs)


async def restart_instance(
    ctx: RunContext[Seat], instance_id: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Restart one instance, e.g. order-gateway-2. evidence_refs: the evidence_ref values that justify it."""
    return _act(ctx, "restart_instance", instance_id, evidence_refs)


async def isolate_instance(
    ctx: RunContext[Seat], instance_id: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Take one instance out of service. evidence_refs: the evidence_ref values that justify it."""
    return _act(ctx, "isolate_instance", instance_id, evidence_refs)


async def failover(
    ctx: RunContext[Seat], component: str, site: str, evidence_refs: list[str]
) -> dict[str, Any]:
    """Move a component to another site (A, B or C). evidence_refs: the evidence_ref values that justify it."""
    return _act(ctx, "failover", f"{component}:{site}", evidence_refs)


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    function.__name__: function
    for function in (
        read_metrics,
        read_logs,
        check_link,
        recent_changes,
        exchange_status,
        search_tickets,
        read_ticket,
        action_status,
        rollback_change,
        restart_instance,
        isolate_instance,
        failover,
    )
}


def state_recovered(deps: IncidentDeps) -> bool | None:
    """Whether the incident's component is healthy now, read without moving simulated time."""
    brief = deps.sim.incident_brief()
    alert_id = brief.get("alert_id")
    components = [
        alert.component
        for alert in deps.sim.alerts.alerts
        if alert.alert_id == alert_id
    ]
    if not components:
        return None
    component = deps.sim.state.component(components[0])
    return (
        component.latency_ms < MAX_LATENCY_MS and component.error_rate < MAX_ERROR_RATE
    )


# Lessons ------------------------------------------------------------------------------------


def _request_handoff_id(state: TeamState, role: Role) -> str:
    """The handoff that asked this role, or the newest one for a role nobody asked."""
    asked = [
        handoff.id
        for handoff in state.handoffs
        if handoff.recipient == role and handoff.kind == "request"
    ]
    if asked:
        return asked[-1]
    return state.handoffs[-1].id if state.handoffs else ""


def lesson_toolset(state: TeamState, role: Role) -> FunctionToolset[Any] | None:
    """The lesson tools of one role, or None when the run has no lesson store.

    They sit beside the role's version-file tools and never widen what the role may change: they
    read the role's own lessons, cite the ones it used and propose lessons for the end of the run.
    """
    session = state.lessons.get(role)
    if session is None:
        return None
    sim = state.deps.sim

    def read_lessons(subject: str) -> dict[str, Any]:
        """Lessons your role learned in earlier incidents about a subject (a component name, or "*")."""
        at = sim.clock.timestamp(sim.state.tick)
        return {"lessons": session.read(subject, at)}

    def cite_lessons(
        lesson_ids: list[str], evidence_refs: list[str] | None = None
    ) -> dict[str, Any]:
        """Record the lessons you actually used, with the evidence_ref values that support them."""
        refs = evidence_refs or []
        unverified = unverified_evidence(state.deps, refs)
        verified = [ref for ref in refs if ref not in unverified]
        handoff_id = _request_handoff_id(state, role)
        return {"cited": session.cite(lesson_ids, handoff_id, verified)}

    def propose_lesson(
        subject: str, text: str, confidence: float = 0.5
    ) -> dict[str, Any]:
        """Propose a lesson for your role from this incident; it is kept after the run is evaluated."""
        mine = [draft for draft in state.drafts if draft.role == role]
        if len(mine) >= MAX_LESSON_DRAFTS_PER_ROLE:
            return {"error": "You already proposed the most lessons allowed."}
        state.drafts.append(
            LessonDraft(
                role=role,
                subject=subject,
                text=text,
                confidence=max(0.0, min(1.0, confidence)),
                created_at=sim.clock.timestamp(state.started_tick),
            )
        )
        return {"proposed": True}

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(read_lessons)
    toolset.add_function(cite_lessons)
    toolset.add_function(propose_lesson)
    return toolset
