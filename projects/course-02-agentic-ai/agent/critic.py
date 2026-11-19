"""The critic: reads a team run's compact trace view and blames one agent on one span.

The view comes from `app.core.team_trace.critic_view` (check labels and verdicts only). A blame
that cites a span outside the blamed agent's invocation is sent back to the model to fix.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from models import Blame
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from app.core.team_trace import (
    BlameRejected,
    RoleVerdict,
    TeamTrace,
    critic_view,
    validate_blame,
)

CRITIC_INSTRUCTIONS = """\
You review one run of an incident team (orchestrator, network, database, remediation, reviewer).
You receive a compact view of the run: case check verdicts, role checks, each agent's answer,
handoffs and tool calls, each with a span_id.
Name the ONE agent whose behaviour most explains the failure. Cite the span_id of the handoff or
tool call that shows it, and it must lie inside that agent's own work (a handoff the orchestrator
made belongs to the orchestrator). Say what went wrong and what that agent should do differently.
"""


def build_critic(
    model: Any, instructions: str = CRITIC_INSTRUCTIONS
) -> Agent[TeamTrace, Blame]:
    agent = Agent(
        model,
        deps_type=TeamTrace,
        output_type=Blame,
        instructions=instructions,
        retries=2,
    )

    @agent.output_validator
    def blame_is_in_trace(ctx: RunContext[TeamTrace], blame: Blame) -> Blame:
        try:
            return validate_blame(ctx.deps, blame)
        except BlameRejected as rejection:
            raise ModelRetry(str(rejection)) from rejection

    return agent


def blame_run(
    model: Any,
    trace: TeamTrace,
    role_verdicts: Sequence[RoleVerdict] = (),
    instructions: str = CRITIC_INSTRUCTIONS,
) -> Blame:
    """The critic's validated blame for one run; raises when it never cites a real span."""
    agent = build_critic(model, instructions)
    view = critic_view(trace, role_verdicts)
    result = agent.run_sync(view, deps=trace, usage_limits=UsageLimits(request_limit=4))
    return result.output
