"""The parts of the version loop that think: the proposer, the offline critic and proposer, and the
trusted check that turns a proposal into a candidate version.

The critic itself lives in agent/critic.py. Nothing here reads checks, validation runs or the
test split: the loop passes in only what the agents may see.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import yaml
from agent.models import (
    Attempt,
    Blame,
    EditInstructions,
    EditMaxRequests,
    EditMaxToolCalls,
    EditVerifyRecovery,
    FieldEdit,
    Proposal,
)
from agent.suite import version_text
from agent.versions import (
    MAX_REQUESTS_CEILING,
    MAX_TOOL_CALLS_CEILING,
    ROLE_TOOL_CATALOG,
    Role,
    RoleVersion,
)
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import infer_model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import UsageLimits

from app.core.model_budget import BudgetedModel, ModelBudget

OFFLINE = "offline"
# The reviewer keeps checking real state, so no proposal may aim at it. Topology is not a field
# of any version file, so it cannot be proposed at all.
UNPROPOSABLE_ROLES: tuple[Role, ...] = ("reviewer",)
MAX_INSTRUCTIONS_CHARS = 4000
PROPOSER_CALL_LIMIT = 4
CURRENT_VERSION_MARKER = "CURRENT VERSION"
EARLIER_ATTEMPTS_MARKER = "EARLIER ATTEMPTS"

PROPOSER_INSTRUCTIONS = """\
You improve one agent of an incident team by editing its version file. You receive the agent's
current version file, the critic's validated blames of that agent on training failures, and a
summary of earlier attempts. Propose exactly ONE edit to ONE field of that agent: instructions
(the complete new text), tools (a subset of its catalog), max_requests, max_tool_calls or
verify_recovery (remediation only). Address the blames. Do not repeat an earlier attempt.
"""


class ProposalRejected(ValueError):
    """The proposal is not one the loop may stage."""


# Models ----------------------------------------------------------------------------------------


def team_model(name: str, budget: ModelBudget) -> Any:
    """The model the team runs on: the offline marker, or the named model behind the budget."""
    if name == OFFLINE:
        return OFFLINE
    return BudgetedModel(infer_model(name), budget)


def agent_model(name: str, offline_stub: FunctionModel, budget: ModelBudget) -> Any:
    """The model of the critic or the proposer: its offline stub, or the named model."""
    if name == OFFLINE:
        return offline_stub
    return BudgetedModel(infer_model(name), budget)


# Offline stubs ---------------------------------------------------------------------------------

TOOL_LINE = re.compile(r"^\s+([0-9a-f]+) t\S+ (\w+) \w+ args:", re.MULTILINE)
HANDOFF_LINE = re.compile(r"^\s+([0-9a-f]+) (\w+) -> \w+ ask:", re.MULTILINE)
FAILED_ROLE_CHECK = re.compile(r"^\s+(\w+) \w+ FAIL:", re.MULTILINE)


def _prompt_text(messages: Sequence[ModelMessage]) -> str:
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


def _retries(messages: Sequence[ModelMessage]) -> int:
    return sum(
        isinstance(part, RetryPromptPart)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def _answer(info: AgentInfo, arguments: dict[str, Any]) -> ModelResponse:
    tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(tool.name, arguments)])


def _blame_candidates(view: str) -> list[tuple[str, str]]:
    """(role, span_id) pairs to try, the roles whose own check failed first."""
    calls = [(role, span) for span, role in TOOL_LINE.findall(view)]
    handoffs = [(role, span) for span, role in HANDOFF_LINE.findall(view)]
    failed_roles = FAILED_ROLE_CHECK.findall(view)
    first = [
        pair for role in failed_roles for pair in reversed(calls) if pair[0] == role
    ]
    return [*first, *handoffs, *reversed(calls)]


def _offline_critic(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    candidates = _blame_candidates(_prompt_text(messages))
    if not candidates:
        return _answer(
            info,
            {
                "role": "orchestrator",
                "span_id": "none",
                "problem": "no span",
                "fix_hint": "",
            },
        )
    # Each retry means the last pick was rejected, so move on to the next one.
    role, span_id = candidates[_retries(messages) % len(candidates)]
    return _answer(
        info,
        {
            "role": role,
            "span_id": span_id,
            "problem": f"{role} did not reach a passing outcome in this run",
            "fix_hint": f"{role} should check its evidence once more before it answers",
        },
    )


def offline_critic() -> FunctionModel:
    return FunctionModel(_offline_critic, model_name=f"{OFFLINE}-critic")


SECTION_HEADINGS = (CURRENT_VERSION_MARKER, "BLAMES (", EARLIER_ATTEMPTS_MARKER)


def _section(text: str, heading: str) -> str:
    """The lines under `heading`, up to the next heading."""
    start = text.find(heading)
    if start < 0:
        return ""
    body_start = text.index("\n", start) + 1
    ends = [
        found
        for other in SECTION_HEADINGS
        if other != heading and (found := text.find("\n" + other, body_start)) >= 0
    ]
    return text[body_start : min(ends, default=len(text))]


def _offline_edits(role: Role, version: RoleVersion) -> list[FieldEdit]:
    edits: list[FieldEdit] = []
    if role == "remediation" and not version.verify_recovery:
        edits.append(EditVerifyRecovery(field="verify_recovery", value=True))
    if version.max_tool_calls + 2 <= MAX_TOOL_CALLS_CEILING:
        edits.append(
            EditMaxToolCalls(field="max_tool_calls", value=version.max_tool_calls + 2)
        )
    if version.max_requests + 4 <= MAX_REQUESTS_CEILING:
        edits.append(
            EditMaxRequests(field="max_requests", value=version.max_requests + 4)
        )
    extra = " Name the affected component and quote ids exactly."
    edits.append(
        EditInstructions(
            field="instructions", value=version.instructions.rstrip() + extra
        )
    )
    return edits


def _offline_proposer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    text = _prompt_text(messages)
    role_match = re.search(r"^ROLE: (\w+)", text, re.MULTILINE)
    version_text = _section(text, CURRENT_VERSION_MARKER)
    history = _section(text, EARLIER_ATTEMPTS_MARKER)
    role: Role = role_match.group(1) if role_match else "network"  # type: ignore[assignment]
    version = RoleVersion(role=role, version="current", **yaml.safe_load(version_text))
    proposals = [
        Proposal(role=role, edit=edit, rationale="deterministic offline proposer")
        for edit in _offline_edits(role, version)
    ]
    untried = [item for item in proposals if item.summary not in history]
    chosen = (untried or proposals)[0]
    return _answer(info, chosen.model_dump(mode="json"))


def offline_proposer() -> FunctionModel:
    return FunctionModel(_offline_proposer, model_name=f"{OFFLINE}-proposer")


# Proposer --------------------------------------------------------------------------------------


def attempt_summary(attempt: Attempt) -> str | None:
    """One line for the proposer. It names the change and the training result, and says only
    whether the candidate was adopted: validation detail stays with the trusted code."""
    decision = attempt.decision
    if attempt.status != "decided" or attempt.change is None or decision is None:
        return None
    before = decision.train_baseline_rate
    after = decision.train_candidate_rate
    training = (
        "training n/a"
        if before is None or after is None
        else f"training {before:.0%} to {after:.0%}"
    )
    verdict = "adopted" if decision.adopt else "not adopted"
    return f"- {attempt.change.summary}; {training}; {verdict}"


def proposer_message(
    version: RoleVersion, blames: Sequence[tuple[str, Blame]], earlier: Sequence[str]
) -> str:
    """Everything the proposer sees. `blames` pairs a training case id with its validated blame."""
    catalog = ", ".join(ROLE_TOOL_CATALOG[version.role])
    blame_lines = [
        f"- case {case_id}, span {blame.span_id}: {blame.problem} Fix: {blame.fix_hint}"
        for case_id, blame in blames
    ]
    return "\n".join(
        [
            f"ROLE: {version.role}",
            f"Limits: max_requests <= {MAX_REQUESTS_CEILING}, max_tool_calls <= {MAX_TOOL_CALLS_CEILING}.",
            f"Tool catalog: {catalog}",
            "",
            f"{CURRENT_VERSION_MARKER} ({version.version}):",
            version_text(version).rstrip(),
            "",
            "BLAMES (validated, training failures):",
            *(blame_lines or ["- none"]),
            "",
            f"{EARLIER_ATTEMPTS_MARKER} (this agent):",
            *(earlier or ["- none"]),
        ]
    )


def propose(model: Any, message: str) -> Proposal:
    """One typed edit from the proposer; it has no tools and sees only `message`."""
    agent = Agent(
        model, output_type=Proposal, instructions=PROPOSER_INSTRUCTIONS, retries=2
    )
    result = agent.run_sync(
        message, usage_limits=UsageLimits(request_limit=PROPOSER_CALL_LIMIT)
    )
    return result.output


# Trusted validation ----------------------------------------------------------------------------


def apply_proposal(
    current: RoleVersion, proposal: Proposal, *, target: Role, next_version: str
) -> RoleVersion:
    """The candidate version the proposal describes, or ProposalRejected."""
    if target in UNPROPOSABLE_ROLES:
        raise ProposalRejected(f"the {target} role cannot be a target")
    if proposal.role != target:
        raise ProposalRejected(f"the proposal targets {proposal.role}, not {target}")
    edit = proposal.edit
    if edit.value == getattr(current, edit.field):
        raise ProposalRejected(f"{edit.field} already has that value")
    if isinstance(edit, EditInstructions) and len(edit.value) > MAX_INSTRUCTIONS_CHARS:
        raise ProposalRejected(
            f"instructions exceed {MAX_INSTRUCTIONS_CHARS} characters"
        )
    content = current.model_dump()
    content[edit.field] = edit.value
    content["version"] = next_version
    try:
        return RoleVersion.model_validate(content)
    except ValidationError as failure:
        raise ProposalRejected(
            json.dumps(failure.errors(include_url=False), default=str)
        ) from failure
