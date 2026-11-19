"""The incident team on the workbench: five agents, typed handoffs, two topologies.

Each agent is a PydanticAI agent named exactly like its role, so its `invoke_agent` span carries
`gen_ai.agent.name=<role>`. In the orchestrator topology the specialists run inside the
orchestrator's `ask_<role>` tool calls, so their spans nest under the tool call; the pipeline runs
the same calls in Python. Both topologies use `invoke_role`, one simulator and one request budget.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Literal

from agent.lessons import LessonSession, lesson_run_id
from agent.offline import is_offline, offline_model
from agent.team_tools import (
    MAX_ERROR_RATE,
    MAX_LATENCY_MS,
    TOOL_FUNCTIONS,
    ReviewFact,
    RoleResult,
    Seat,
    TeamState,
    lesson_toolset,
    state_recovered,
)
from agent.versions import ROLES, Role, TeamVersion
from opentelemetry import trace
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits

from meridian.agent_runtime import IncidentDeps

SPECIALISTS: tuple[Role, ...] = ("network", "database", "remediation", "reviewer")
HEALTHY_READINGS = 3
TRACER = trace.get_tracer("meridian.team")

# What the agents return ------------------------------------------------------------------------


class NetworkFinding(BaseModel):
    cause: str = Field(description="The cause; names the affected component.")
    components: list[str] = Field(description="The affected components.")
    evidence: list[str] = Field(description="evidence_ref values and quoted ids.")


class Finding(BaseModel):
    cause: str
    evidence: list[str]
    constraints: list[str] = Field(
        description="Facts that limit what the others may do, e.g. a maintenance window."
    )


class RemediationReport(BaseModel):
    status: Literal["resolved", "unresolved"]
    actions: list[str]
    summary: str


class Review(BaseModel):
    status: Literal["resolved", "unresolved"]
    reason: str

    @property
    def recovered(self) -> bool:
        return self.status == "resolved"


class Outcome(BaseModel):
    """What the team reports at the end."""

    status: Literal["resolved", "unresolved"]
    root_cause: str
    summary: str


ROLE_OUTPUT: dict[Role, type[BaseModel]] = {
    "orchestrator": Outcome,
    "network": NetworkFinding,
    "database": Finding,
    "remediation": RemediationReport,
    "reviewer": Review,
}

# Building ----------------------------------------------------------------------------------------


def resolve_model(model: Any, role: Role) -> Any:
    """The offline stub for the offline marker or pydantic's TestModel, else the model itself."""
    if is_offline(model):
        return offline_model(role)
    return model


def _component_of_alert(deps: IncidentDeps) -> str | None:
    alert_id = deps.sim.incident_brief().get("alert_id")
    for alert in deps.sim.alerts.alerts:
        if alert.alert_id == alert_id:
            return alert.component
    return None


def verify_recovery(
    ctx: RunContext[Seat], report: RemediationReport
) -> RemediationReport:
    """Output validator: "resolved" needs healthy readings of the incident's component."""
    if report.status != "resolved":
        return report
    component = _component_of_alert(ctx.deps.deps)
    if component is None:
        return report
    metrics = ctx.deps.deps.tools.read_metrics(component, HEALTHY_READINGS)
    if "error" in metrics:
        raise ModelRetry(
            f"Recovery cannot be confirmed: {metrics['error']}. Do not report resolved."
        )
    bad = [
        reading
        for reading in metrics["readings"]
        if reading["latency_ms"] >= MAX_LATENCY_MS
        or reading["error_rate"] >= MAX_ERROR_RATE
    ]
    if bad:
        raise ModelRetry(
            f"Recovery not confirmed on {component}: latency_ms={bad[-1]['latency_ms']}, "
            f"error_rate={bad[-1]['error_rate']}. Read the metrics again after acting, "
            "and report unresolved if they are still unhealthy."
        )
    return report


def build_role_agent(role: Role, model: Any, team: TeamVersion) -> Agent[Seat, Any]:
    version = team.roles[role]
    agent: Agent[Seat, Any] = Agent(
        resolve_model(model, role),
        name=role,
        deps_type=Seat,
        output_type=ROLE_OUTPUT[role],
        instructions=version.instructions,
        tools=[TOOL_FUNCTIONS[name] for name in version.tools],
        retries=3,
    )
    if role == "remediation" and version.verify_recovery:
        agent.output_validator(verify_recovery)
    return agent


class TeamAgent(Agent[IncidentDeps, Outcome]):
    """The orchestrator agent, carrying the team it belongs to."""

    team: TeamVersion
    specialists: dict[Role, Agent[Seat, Any]]


def _lesson_sessions(deps: IncidentDeps) -> dict[Role, LessonSession]:
    """One session per role when the run keeps lessons: it has a store and a run id."""
    run_id = deps.scratch.get("run_id")
    if deps.memory is None or run_id is None:
        return {}
    origin = lesson_run_id(run_id, deps.sim.scenario.scenario_id)
    return {role: LessonSession(deps.memory, role, origin) for role in ROLES}


def team_state(agent: TeamAgent, deps: IncidentDeps) -> TeamState:
    """The run's team state, created on first use and kept on the run's dependencies."""
    if "team" not in deps.scratch:
        sender = "orchestrator" if agent.team.topology == "orchestrator" else "pipeline"
        state = TeamState(
            version=agent.team,
            deps=deps,
            agents=dict(agent.specialists),
            sender=sender,
            lessons=_lesson_sessions(deps),
            started_tick=deps.sim.state.tick,
        )
        deps.scratch["team"] = state
    return deps.scratch["team"]


def scratch_state(scratch: dict[str, Any]) -> TeamState | None:
    """The team state of a finished run, read from its dependencies' scratch."""
    return scratch.get("team")


def _ask_toolset(
    agent_holder: list[TeamAgent], names: Sequence[str]
) -> FunctionToolset[IncidentDeps]:
    toolset: FunctionToolset[IncidentDeps] = FunctionToolset()

    def add(role: Role, description: str) -> None:
        async def ask(ctx: RunContext[IncidentDeps], request: str) -> dict[str, Any]:
            state = team_state(agent_holder[0], ctx.deps)
            state.bind_usage(ctx.usage, ctx.usage_limits)
            result = await invoke_role(role, request, state=state)
            return result.model_dump(exclude_none=True)

        ask.__name__ = f"ask_{role}"
        ask.__doc__ = description
        if ask.__name__ in names:
            toolset.add_function(ask, name=ask.__name__)

    add(
        "network",
        "Ask the network specialist: links, recent changes, the affected component's logs. It changes nothing.",
    )
    add(
        "database",
        "Ask the database specialist: reference-db health, logs, planned work and maintenance windows. It changes nothing.",
    )
    add(
        "remediation",
        "Give remediation a task: what to do, why, the affected component, and the constraints to respect. It acts under approval.",
    )
    add(
        "reviewer",
        "Ask the reviewer to check the real state and say whether the incident is over.",
    )
    return toolset


def build_team_agent(model: Any, team: TeamVersion) -> TeamAgent:
    specialists: dict[Role, Agent[Seat, Any]] = {
        role: build_role_agent(role, model, team) for role in SPECIALISTS
    }
    holder: list[TeamAgent] = []
    version = team.roles["orchestrator"]
    agent = TeamAgent(
        resolve_model(model, "orchestrator"),
        name="orchestrator",
        deps_type=IncidentDeps,
        output_type=Outcome,
        instructions=version.instructions,
        toolsets=[_ask_toolset(holder, version.tools)],
        retries=3,
    )
    agent.team = team
    agent.specialists = specialists
    holder.append(agent)
    return agent


# Invoking a role ---------------------------------------------------------------------------------


def _render(answer: BaseModel) -> dict[str, Any]:
    return answer.model_dump(mode="json")


def _no_answer(
    state: TeamState, role: Role, reason: str, requests: int, refs: list[str]
) -> RoleResult:
    text = f"No answer: {role} stopped without finishing ({reason})."
    handoff = state.record_handoff(
        role, state.sender, "no_answer", {"reason": text}, refs
    )
    return RoleResult(
        role=role,
        handoff_id=handoff.id,
        status="no_answer",
        reason=text,
        evidence_refs=refs,
        requests=requests,
    )


def _request_limit(state: TeamState, role: Role) -> UsageLimits:
    """The role's own remaining requests, inside the run's shared budget."""
    assert state.usage is not None
    remaining = state.version.roles[role].max_requests - state.requests[role]
    limit = state.usage.requests + remaining
    if state.request_limit is not None:
        limit = min(limit, state.request_limit)
    return UsageLimits(request_limit=limit)


def _extra_toolsets(*toolsets: Any) -> list[Any] | None:
    present = [toolset for toolset in toolsets if toolset is not None]
    return present or None


async def invoke_role(role: Role, request: str, *, state: TeamState) -> RoleResult:
    """Run one specialist on one request and return its answer, or an explicit no-answer."""
    if state.usage is None:
        state.usage = RunUsage()
    span = trace.get_current_span()
    asked = state.record_handoff(state.sender, role, "request", {"text": request})
    span.set_attributes(
        {"meridian.role": role, "meridian.request_handoff_id": asked.id}
    )
    if state.requests[role] >= state.version.roles[role].max_requests:
        return _no_answer(state, role, "its request limit is used", 0, [])

    seat = Seat(state.deps, role, state)
    output: BaseModel | None = None
    failure = ""
    with capture_run_messages() as messages:
        try:
            run = await state.agents[role].run(
                request,
                deps=seat,
                usage=state.usage,
                usage_limits=_request_limit(state, role),
                toolsets=_extra_toolsets(lesson_toolset(state, role)),
            )
            output = run.output
        except AgentRunError as error:
            failure = str(error)
    requests = sum(1 for message in messages if isinstance(message, ModelResponse))
    state.requests[role] += requests
    state.deps.extra_messages.extend(messages)

    if output is None:
        result = _no_answer(state, role, failure, requests, seat.refs)
    else:
        handoff = state.record_handoff(
            role, state.sender, "result", _render(output), seat.refs
        )
        result = RoleResult(
            role=role,
            handoff_id=handoff.id,
            status="answered",
            answer=_render(output),
            evidence_refs=seat.refs,
            requests=requests,
        )
    span.set_attributes(
        {
            "meridian.handoff_id": result.handoff_id,
            "meridian.handoff_status": result.status,
            "meridian.tick": state.deps.sim.state.tick,
        }
    )
    if role == "reviewer":
        _record_review(state, result, span)
    return result


def _record_review(state: TeamState, result: RoleResult, span: trace.Span) -> None:
    """Keep the reviewer's verdict next to the real state at the same tick."""
    recovered = state_recovered(state.deps)
    status = str((result.answer or {}).get("status", "no_answer"))
    tick = state.deps.sim.state.tick
    state.reviews.append(
        ReviewFact(tick=tick, state_recovered=recovered, reviewer_status=status)
    )
    span.set_attribute("meridian.reviewer_status", status)
    if recovered is not None:
        span.set_attribute("meridian.state_recovered", recovered)


# The pipeline ------------------------------------------------------------------------------------


def _text(result: RoleResult) -> str:
    if result.status == "no_answer":
        return result.reason
    return "; ".join(f"{key}: {value}" for key, value in (result.answer or {}).items())


async def _step(role: Role, request: str, state: TeamState) -> RoleResult:
    with TRACER.start_as_current_span(
        "meridian.handoff", attributes={"meridian.role": role}
    ):
        return await invoke_role(role, request, state=state)


async def run_pipeline(
    agent: TeamAgent, prompt: str, deps: IncidentDeps, limits: UsageLimits
) -> Outcome:
    """Network and database investigate, remediation acts, the reviewer checks; one correction at most."""
    state = team_state(agent, deps)
    state.usage = RunUsage()
    state.request_limit = limits.request_limit
    network = await _step("network", f"{prompt}\nFind the cause.", state)
    database = await _step(
        "database", f"{prompt}\nFind the cause and any constraint.", state
    )
    findings = f"Network: {_text(network)}\nDatabase: {_text(database)}"
    task = f"{prompt}\nFindings:\n{findings}\nMitigate the incident, respecting every constraint."
    remediation = await _step("remediation", task, state)
    review = await _step(
        "reviewer", f"{prompt}\nIs the incident over? Check the real state.", state
    )
    if (review.answer or {}).get("status") != "resolved":
        correction = f"{task}\nThe reviewer says the incident is not over: {_text(review)} Fix it if you safely can."
        remediation = await _step("remediation", correction, state)
        review = await _step(
            "reviewer",
            f"{prompt}\nIs the incident over now? Check the real state.",
            state,
        )
    recovered = (review.answer or {}).get("status") == "resolved"
    cause = (network.answer or {}).get("cause") or "no answer from network"
    return Outcome(
        status="resolved" if recovered else "unresolved",
        root_cause=str(cause),
        summary=f"Remediation: {_text(remediation)} Review: {_text(review)}",
    )


def run_sync(
    agent: TeamAgent,
    prompt: str,
    deps: IncidentDeps,
    limits: UsageLimits,
    toolsets: Any,
) -> Outcome:
    if agent.team.topology == "pipeline":
        return asyncio.run(run_pipeline(agent, prompt, deps, limits))
    state = team_state(agent, deps)
    lessons = lesson_toolset(state, "orchestrator")
    extra = _extra_toolsets(*(toolsets or []), lessons)
    result = agent.run_sync(prompt, deps=deps, usage_limits=limits, toolsets=extra)
    return result.output
