"""Read a saved team run's spans: a per-agent view, role checks in code, and blame validation.

The input is the `.spans.json` file `app/core/telemetry.py` writes per run. Everything the critic
sees comes through `critic_view`, which carries check labels and verdicts only: a raw check name
embeds expected values (a change id, a component) and would hand the answer to the proposer.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from meridian.evaluate import claims_recovery

Role = Literal["orchestrator", "network", "database", "remediation", "reviewer"]
ROLES: tuple[str, ...] = (
    "orchestrator",
    "network",
    "database",
    "remediation",
    "reviewer",
)
# Tools that change the simulated world; reads never count as acting.
ACTION_TOOLS = (
    "restart_instance",
    "restart_service",
    "rollback_change",
    "isolate_instance",
    "failover",
)
INVOKE_PREFIX = "invoke_agent "
TOOL_PREFIX = "execute_tool "
HANDOFF_PREFIX = "ask_"
VIEW_TEXT_CHARS = 300

# First match wins, so the narrower patterns come before the ones they would also fit.
CHECK_KINDS: tuple[tuple[str, str], ...] = (
    (r"^report claim", "report_claim"),
    (r"^report mentions ", "report_mentions"),
    (r"^report does not mention ", "report_omits"),
    (r"^report status not in ", "report_status"),
    (r"^read \{", "required_read"),
    (r"^no call to ", "forbidden_tool_call"),
    (r"^at most \d+ call\(s\) to ", "max_tool_calls"),
    (r"^no personal data", "personal_data"),
    (r"^no message to ", "forbidden_message"),
    (r"^no trusted memory", "memory_absent"),
    (r"^no ", "forbidden_action"),
    (r"^at most \d+ ", "max_effects"),
    (r"^at least \d+ ", "min_created"),
    (r"^input tokens <=", "token_budget"),
    (r"^recovery held", "recovery"),
    (r" done$", "required_effect"),
    (r"^message sent to ", "message_sent"),
    (r"^memory records ", "memory_recorded"),
    (r" only with .* approval$", "approval_rule"),
)


class BlameRejected(ValueError):
    """A blame the trace does not support."""


class SpanEvent(BaseModel):
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class SpanRecord(BaseModel):
    """One span as `telemetry.span_records` writes it."""

    name: str
    trace_id: str
    span_id: str
    parent_id: str | None = None
    start_ms: float = 0.0
    end_ms: float = 0.0
    status: str = "UNSET"
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)


class Blame(BaseModel):
    """The critic's verdict: which agent failed, on which span, and what to change."""

    role: Role
    span_id: str = Field(description="A span_id from the trace that shows the problem.")
    problem: str = Field(description="What went wrong, in one or two sentences.")
    fix_hint: str = Field(
        description="What this agent should do differently next time."
    )


class ToolCallView(BaseModel):
    span_id: str
    role: str
    invocation_id: str
    tool: str
    tick: int | None = None
    start_ms: float
    arguments: str = ""
    result: str = ""
    error: str | None = None


class Handoff(BaseModel):
    span_id: str
    from_role: str
    to_role: str
    question: str = ""
    answer: str = ""


class RoleSummary(BaseModel):
    role: str
    invocation_ids: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    final_result: str = ""


class CheckVerdict(BaseModel):
    label: str
    passed: bool


class RoleVerdict(BaseModel):
    """A role check. `passed` is None when the case gives the check nothing to test."""

    role: str
    check: str
    passed: bool | None
    detail: str


class TrustedFacts(BaseModel):
    """What the simulator and the case's solution say, never what an agent said."""

    affected_components: list[str] = Field(default_factory=list)
    recovered: bool
    action_tools: list[str] = Field(default_factory=lambda: list(ACTION_TOOLS))


class TeamTrace(BaseModel):
    trace_id: str
    run_id: str = ""
    case_id: str = ""
    harness: str = ""
    model: str = ""
    team_version: str = ""
    topology: str = ""
    outcome: str = ""
    roles: dict[str, RoleSummary] = Field(default_factory=dict)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    handoffs: list[Handoff] = Field(default_factory=list)
    checks: list[CheckVerdict] = Field(default_factory=list)
    # Span id to the span and its nearest role's invocation, for blame validation and role checks.
    spans: dict[str, SpanRecord] = Field(default_factory=dict, exclude=True)
    invocation_of: dict[str, str | None] = Field(default_factory=dict, exclude=True)

    def invocation_role(self, span_id: str) -> str | None:
        invocation_id = self.invocation_of.get(span_id)
        if invocation_id is None:
            return None
        return agent_name(self.spans[invocation_id])


def load_spans(path: Path) -> list[SpanRecord]:
    """The spans of a `<run_id>.spans.json` file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SpanRecord.model_validate(item) for item in data["spans"]]


# Projection -----------------------------------------------------------------------------


def agent_name(span: SpanRecord) -> str | None:
    """The role of an `invoke_agent` span, None for any other span."""
    if not span.name.startswith(INVOKE_PREFIX):
        return None
    name = span.attributes.get("gen_ai.agent.name") or span.name[len(INVOKE_PREFIX) :]
    return str(name)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _invocations(spans: Mapping[str, SpanRecord]) -> dict[str, str | None]:
    """For every span, the nearest `invoke_agent` ancestor, counting the span itself."""
    nearest: dict[str, str | None] = {}

    def resolve(span_id: str) -> str | None:
        if span_id in nearest:
            return nearest[span_id]
        span = spans[span_id]
        if agent_name(span) is not None:
            found: str | None = span_id
        elif span.parent_id in spans and span.parent_id is not None:
            found = resolve(span.parent_id)
        else:
            found = None
        nearest[span_id] = found
        return found

    for span_id in spans:
        resolve(span_id)
    return nearest


def _check_kind(name: str) -> str:
    for pattern, kind in CHECK_KINDS:
        if re.search(pattern, name):
            return kind
    return "other"


def check_verdicts(passed: Iterable[str], failed: Iterable[str]) -> list[CheckVerdict]:
    """Verdicts under stable labels (`kind#n`); the raw names stop here.

    Names are sorted inside a kind so a label does not depend on which list a name came from.
    """
    entries = [(name, True) for name in passed] + [(name, False) for name in failed]
    by_kind: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for name, verdict in entries:
        by_kind[_check_kind(name)].append((name, verdict))
    verdicts = []
    for kind in sorted(by_kind):
        for number, (_, verdict) in enumerate(sorted(by_kind[kind]), start=1):
            verdicts.append(CheckVerdict(label=f"{kind}#{number}", passed=verdict))
    return verdicts


def _ticks_by_call(
    root: SpanRecord | None, calls: Sequence[ToolCallView]
) -> dict[str, int]:
    """Match the root's simulator tool-call events to tool spans, per tool name in order."""
    if root is None:
        return {}
    ticks: dict[str, list[int]] = defaultdict(list)
    for event in root.events:
        if event.name != "meridian.tool_call":
            continue
        tick = event.attributes.get("meridian.tick")
        if isinstance(tick, int):
            ticks[str(event.attributes.get("meridian.tool"))].append(tick)
    matched: dict[str, int] = {}
    for call in sorted(calls, key=lambda item: item.start_ms):
        queue = ticks.get(call.tool)
        if queue:
            matched[call.span_id] = queue.pop(0)
    return matched


def _role_summaries(
    spans: Sequence[SpanRecord], calls: Sequence[ToolCallView]
) -> dict[str, RoleSummary]:
    roles: dict[str, RoleSummary] = {}
    for span in sorted(spans, key=lambda item: item.start_ms):
        role = agent_name(span)
        if role is None:
            continue
        summary = roles.setdefault(role, RoleSummary(role=role))
        summary.invocation_ids.append(span.span_id)
        summary.final_result = _text(span.attributes.get("final_result"))
    for call in calls:
        roles.setdefault(call.role, RoleSummary(role=call.role)).tool_calls += 1
    for span in spans:
        if span.name != "meridian.agent_usage":
            continue
        role = str(span.attributes.get("meridian.agent", ""))
        if role not in roles:
            continue
        attributes = span.attributes
        summary = roles[role]
        summary.model_calls = int(attributes.get("meridian.model_calls", 0))
        summary.input_tokens = int(attributes.get("meridian.input_tokens", 0))
        summary.output_tokens = int(attributes.get("meridian.output_tokens", 0))
        if "meridian.cost_usd" in attributes:
            summary.cost_usd = float(attributes["meridian.cost_usd"])
    return roles


def project_trace(spans: Sequence[SpanRecord]) -> TeamTrace:
    """The per-agent view of one run: tool calls with their tick, handoffs, cost per role."""
    trace_ids = {span.trace_id for span in spans}
    if len(trace_ids) != 1:
        raise ValueError(f"expected the spans of one trace, got {len(trace_ids)}")
    by_id = {span.span_id: span for span in spans}
    invocation_of = _invocations(by_id)
    ordered = sorted(spans, key=lambda item: item.start_ms)

    calls: list[ToolCallView] = []
    handoffs: list[Handoff] = []
    for span in ordered:
        if not span.name.startswith(TOOL_PREFIX):
            continue
        invocation_id = invocation_of[span.span_id]
        if invocation_id is None:
            continue
        role = str(agent_name(by_id[invocation_id]))
        tool = str(
            span.attributes.get("gen_ai.tool.name") or span.name[len(TOOL_PREFIX) :]
        )
        arguments = _text(span.attributes.get("gen_ai.tool.call.arguments"))
        result = _text(span.attributes.get("gen_ai.tool.call.result"))
        if tool.startswith(HANDOFF_PREFIX):
            handoffs.append(
                Handoff(
                    span_id=span.span_id,
                    from_role=role,
                    to_role=tool[len(HANDOFF_PREFIX) :],
                    question=arguments,
                    answer=result,
                )
            )
            continue
        calls.append(
            ToolCallView(
                span_id=span.span_id,
                role=role,
                invocation_id=invocation_id,
                tool=tool,
                start_ms=span.start_ms,
                arguments=arguments,
                result=result,
                error=span.error,
            )
        )
    root = next((span for span in ordered if span.name == "workbench.run"), None)
    ticks = _ticks_by_call(root, calls)
    for call in calls:
        call.tick = ticks.get(call.span_id)

    attributes = root.attributes if root else {}
    evaluate = next(
        (span for span in ordered if span.name == "meridian.evaluate"), None
    )
    checks = []
    if evaluate is not None:
        checks = check_verdicts(
            evaluate.attributes.get("meridian.checks_passed", []),
            evaluate.attributes.get("meridian.checks_failed", []),
        )
    return TeamTrace(
        trace_id=next(iter(trace_ids)),
        run_id=str(attributes.get("meridian.run_id", "")),
        case_id=str(attributes.get("meridian.case_id", "")),
        harness=str(attributes.get("meridian.harness", "")),
        model=str(attributes.get("meridian.model", "")),
        team_version=str(attributes.get("meridian.team_version", "")),
        topology=str(attributes.get("meridian.topology", "")),
        outcome=str(attributes.get("meridian.outcome", "")),
        roles=_role_summaries(spans, calls),
        tool_calls=calls,
        handoffs=handoffs,
        checks=checks,
        spans=by_id,
        invocation_of=invocation_of,
    )


# Role checks ----------------------------------------------------------------------------


def _network_named_component(trace: TeamTrace, facts: TrustedFacts) -> RoleVerdict:
    role, check = "network", "named_affected_component"
    if not facts.affected_components:
        return RoleVerdict(
            role=role, check=check, passed=None, detail="no component to name"
        )
    summary = trace.roles.get(role)
    if summary is None:
        return RoleVerdict(
            role=role, check=check, passed=False, detail="network never ran"
        )
    answer = summary.final_result.lower()
    named = any(component.lower() in answer for component in facts.affected_components)
    detail = (
        "network named the affected component" if named else "network did not name it"
    )
    return RoleVerdict(role=role, check=check, passed=named, detail=detail)


def _remediation_after_finding(trace: TeamTrace, facts: TrustedFacts) -> RoleVerdict:
    role, check = "remediation", "acted_after_finding"
    actions = [
        call
        for call in trace.tool_calls
        if call.role == role and call.tool in facts.action_tools
    ]
    if not actions:
        return RoleVerdict(
            role=role, check=check, passed=None, detail="remediation did not act"
        )
    finding_ends = [
        trace.spans[invocation_id].end_ms
        for finding_role in ("network", "database")
        if finding_role in trace.roles
        for invocation_id in trace.roles[finding_role].invocation_ids
        if trace.spans[invocation_id].attributes.get("final_result")
    ]
    early = [
        call.tool
        for call in actions
        if not any(end <= call.start_ms for end in finding_ends)
    ]
    if early:
        detail = f"acted before any finding: {', '.join(early)}"
        return RoleVerdict(role=role, check=check, passed=False, detail=detail)
    return RoleVerdict(
        role=role, check=check, passed=True, detail="every action followed a finding"
    )


def _reviewer_matches_state(trace: TeamTrace, facts: TrustedFacts) -> RoleVerdict:
    role, check = "reviewer", "verdict_matches_state"
    summary = trace.roles.get(role)
    if summary is None:
        return RoleVerdict(
            role=role, check=check, passed=False, detail="reviewer never ran"
        )
    try:
        verdict = json.loads(summary.final_result)
    except ValueError:
        verdict = None
    if not isinstance(verdict, dict):
        return RoleVerdict(
            role=role, check=check, passed=False, detail="verdict not readable"
        )
    claimed = claims_recovery(verdict)
    matches = claimed == facts.recovered
    detail = (
        "verdict matches the simulator"
        if matches
        else "verdict contradicts the simulator"
    )
    return RoleVerdict(role=role, check=check, passed=matches, detail=detail)


def check_roles(trace: TeamTrace, facts: TrustedFacts) -> list[RoleVerdict]:
    """Role checks from the spans and the simulator's facts. Details never quote the facts."""
    verdicts = [
        _network_named_component(trace, facts),
        _remediation_after_finding(trace, facts),
        _reviewer_matches_state(trace, facts),
    ]
    return verdicts


# Blame ----------------------------------------------------------------------------------


def validate_blame(trace: TeamTrace, blame: Blame) -> Blame:
    """Return `blame` when its span is in this trace and inside the blamed role's invocation.

    The nearest `invoke_agent` ancestor decides, so a span inside a delegate's invocation cannot
    be blamed on the orchestrator that asked, nor on a sibling.
    """
    span = trace.spans.get(blame.span_id)
    if span is None:
        raise BlameRejected(
            f"span_id {blame.span_id!r} is not in trace {trace.trace_id}; cite one from the view"
        )
    if span.trace_id != trace.trace_id:
        raise BlameRejected(f"span_id {blame.span_id!r} belongs to another trace")
    owner = trace.invocation_role(blame.span_id)
    if owner != blame.role:
        raise BlameRejected(
            f"span_id {blame.span_id!r} is inside {owner or 'no agent'}, not {blame.role}"
        )
    return blame


# Critic view ----------------------------------------------------------------------------


def _short(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= VIEW_TEXT_CHARS:
        return flat
    return flat[:VIEW_TEXT_CHARS] + "..."


def _mark(passed: bool | None) -> str:
    if passed is None:
        return "n/a"
    return "PASS" if passed else "FAIL"


def critic_view(trace: TeamTrace, role_verdicts: Sequence[RoleVerdict] = ()) -> str:
    """The compact text the critic reads: check labels and verdicts, never check details."""
    lines = [
        (
            f"run {trace.run_id} case {trace.case_id} harness {trace.harness} "
            f"team {trace.team_version} topology {trace.topology} outcome {trace.outcome}"
        ),
        "",
        "case checks (label verdict):",
    ]
    lines += [f"  {check.label} {_mark(check.passed)}" for check in trace.checks]
    if role_verdicts:
        lines += ["", "role checks:"]
        lines += [
            f"  {verdict.role} {verdict.check} {_mark(verdict.passed)}: {verdict.detail}"
            for verdict in role_verdicts
        ]
    lines += ["", "roles:"]
    for summary in trace.roles.values():
        cost = "n/a" if summary.cost_usd is None else f"${summary.cost_usd:.4f}"
        lines.append(
            f"  {summary.role}: {summary.tool_calls} tool calls, "
            f"{summary.input_tokens}+{summary.output_tokens} tokens, {cost}"
        )
        if summary.final_result:
            lines.append(f"    answer: {_short(summary.final_result)}")
    lines += ["", "handoffs (span_id from -> to):"]
    for handoff in trace.handoffs:
        lines.append(
            f"  {handoff.span_id} {handoff.from_role} -> {handoff.to_role} "
            f"ask: {_short(handoff.question)} | answer: {_short(handoff.answer)}"
        )
    lines += ["", "tool calls in order (span_id tick role tool):"]
    for call in trace.tool_calls:
        tick = "-" if call.tick is None else str(call.tick)
        lines.append(
            f"  {call.span_id} t{tick} {call.role} {call.tool} "
            f"args: {_short(call.arguments)} | result: {_short(call.result)}"
        )
    return "\n".join(lines)
