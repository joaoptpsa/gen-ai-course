"""Draft training cases from coordination failures.

The author reads the masked failure view of a saved training run (`critic_view`, never check
details) and chooses one failure pattern, a slug and a title. It has no tools and writes nothing.
Code turns that choice into a scenario and a check from the simulator's existing mechanisms, then
rehearses a known-good and a failing team trajectory against the check's coordination section.
The draft is returned for a human to review; admitting it is a separate `cases write`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from agent.coordination import SECTION, evaluate_coordination
from agent.team_tools import Handoff
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import UsageLimits

from app.core import authoring
from app.core.case_splits import TRAIN_ONLY_PREFIXES
from app.core.team_trace import RoleVerdict, TeamTrace, critic_view
from app.paths import CASES_DIR, CHECKS_DIR

SpecialistRole = Literal["network", "database"]
HandoffKind = Literal["request", "result", "no_answer"]
FailureKind = Literal["conflicting_findings", "silent_specialist", "dropped_constraint"]
KIND_SLUG: dict[str, str] = {
    "conflicting_findings": "conflict",
    "silent_specialist": "silent",
    "dropped_constraint": "dropped",
}
CASE_PREFIX = TRAIN_ONLY_PREFIXES[0]
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
OFFLINE_AUTHOR = "offline-case-author"

AUTHOR_INSTRUCTIONS = """\
You design one new training case for an incident team (orchestrator, network, database,
remediation, reviewer) from the compact view of one failed run.
Choose the coordination failure the run shows:
- conflicting_findings: two specialists reported findings that disagree and the team acted anyway;
- silent_specialist: a specialist gave no answer and the rest of the run ignored the gap;
- dropped_constraint: a constraint or evidence reference one specialist found never reached the
  role that acted.
Give a short lowercase slug, a one-line title and the specialist role the failure concerns.
"""


class DraftRejected(ValueError):
    """The draft cannot be offered for review; the message lists every problem found."""


class FailureSummary(BaseModel):
    """One saved failure: the masked view the critic reads and where it came from."""

    set_id: str
    run_id: str
    span_id: str
    split: Literal["train", "valid", "test"] = "train"
    view: str


class CasePlan(BaseModel):
    """What the author chooses; everything else comes from fixed templates."""

    kind: FailureKind
    slug: str = Field(max_length=40)
    title: str = Field(min_length=1, max_length=120)
    role: SpecialistRole = Field(description="The specialist the failure concerns.")


class CheckOutcome(BaseModel):
    name: str
    passed: bool
    detail: str


class Rehearsal(BaseModel):
    """One synthetic trajectory run through the coordination predicates."""

    trajectory: str
    expected_pass: bool
    passed: bool
    checks: list[CheckOutcome]


class CaseDraft(BaseModel):
    """A proposed case and check, with where they came from and how they rehearsed."""

    case_id: str
    kind: FailureKind
    scenario_yaml: str
    check_yaml: str
    source_set_id: str
    source_run_id: str
    source_span_id: str
    rehearsal: list[Rehearsal] = Field(default_factory=list)


def summarize_failure(
    trace: TeamTrace,
    set_id: str,
    span_id: str,
    role_verdicts: Sequence[RoleVerdict] = (),
    split: Literal["train", "valid", "test"] = "train",
) -> FailureSummary:
    """The failure view for one run, built the way the critic reads it."""
    view = critic_view(trace, role_verdicts)
    return FailureSummary(
        set_id=set_id, run_id=trace.run_id, span_id=span_id, split=split, view=view
    )


# Trajectories -------------------------------------------------------------------------------


def _handoffs(
    steps: Sequence[tuple[str, str, HandoffKind, str, Sequence[str]]],
) -> list[Handoff]:
    return [
        Handoff(
            id=f"H-{index:03d}",
            sender=sender,
            recipient=recipient,
            kind=kind,
            payload={"text": text},
            evidence_refs=list(refs),
            tick=index,
        )
        for index, (sender, recipient, kind, text, refs) in enumerate(steps, start=1)
    ]


def _conflict_trajectories(
    spec: dict[str, Any],
) -> list[tuple[str, bool, list[Handoff]]]:
    first, second = spec["reconcile"]["roles"]
    opening = [
        (
            "orchestrator",
            first,
            "request",
            f"Check the {first} side of the incident.",
            [],
        ),
        (first, "orchestrator", "result", "Cause is on my side.", ["read_metrics#1"]),
        (
            "orchestrator",
            second,
            "request",
            f"Check the {second} side of the incident.",
            [],
        ),
        (
            second,
            "orchestrator",
            "result",
            "Cause is on my side, not yours.",
            ["read_metrics#2"],
        ),
    ]
    good = [
        *opening,
        (
            "orchestrator",
            first,
            "request",
            f"The {second} finding conflicts with yours. Re-check.",
            [],
        ),
        (
            first,
            "orchestrator",
            "result",
            "Re-checked, cause confirmed.",
            ["read_logs#3"],
        ),
        (
            "orchestrator",
            "remediation",
            "request",
            "Act on the confirmed cause.",
            ["read_logs#3"],
        ),
    ]
    bad = [
        *opening,
        ("orchestrator", "remediation", "request", "Act on the first finding.", []),
    ]
    return [
        ("reconciled", True, _handoffs(good)),
        ("acted on open conflict", False, _handoffs(bad)),
    ]


def _silent_trajectories(spec: dict[str, Any]) -> list[tuple[str, bool, list[Handoff]]]:
    role = spec["unanswered"]["role"]
    opening = [
        ("orchestrator", role, "request", "Check your side of the incident.", []),
        (
            role,
            "orchestrator",
            "no_answer",
            "No answer: its tools are unavailable.",
            [],
        ),
    ]
    good = [
        *opening,
        (
            "orchestrator",
            "reviewer",
            "request",
            f"{role} gave no answer. Verify recovery cautiously.",
            [],
        ),
    ]
    bad = [
        *opening,
        ("orchestrator", "reviewer", "request", "Verify the recovery.", []),
    ]
    return [
        ("gap carried forward", True, _handoffs(good)),
        ("gap dropped", False, _handoffs(bad)),
    ]


def _constraint_trajectories(
    spec: dict[str, Any],
) -> list[tuple[str, bool, list[Handoff]]]:
    rule = spec["preserve"]
    source, sink, reference = rule["source"], rule["sink"], rule["reference"]
    opening = [
        ("orchestrator", source, "request", "Find the cause and any constraint.", []),
        (
            source,
            "orchestrator",
            "result",
            f"Memory leak; {reference} forbids touching the instance.",
            ["read_ticket#2"],
        ),
    ]
    good = [
        *opening,
        (
            "orchestrator",
            sink,
            "request",
            f"Act within {reference}.",
            ["read_ticket#2"],
        ),
    ]
    bad = [
        *opening,
        ("orchestrator", sink, "request", "Restart the leaking instance.", []),
    ]
    return [
        ("constraint kept", True, _handoffs(good)),
        ("constraint dropped", False, _handoffs(bad)),
    ]


TRAJECTORIES: dict[
    str, Callable[[dict[str, Any]], list[tuple[str, bool, list[Handoff]]]]
] = {
    "conflicting_findings": _conflict_trajectories,
    "silent_specialist": _silent_trajectories,
    "dropped_constraint": _constraint_trajectories,
}


def rehearse(draft: CaseDraft) -> list[Rehearsal]:
    """Run the draft's known-good and failing trajectories through its coordination section."""
    check = yaml.safe_load(draft.check_yaml)
    spec = check[SECTION]
    results: list[Rehearsal] = []
    for name, expected, handoffs in TRAJECTORIES[draft.kind](spec):
        checks = evaluate_coordination(spec, handoffs)
        outcomes = [
            CheckOutcome(name=item.name, passed=item.passed, detail=item.detail)
            for item in checks
        ]
        results.append(
            Rehearsal(
                trajectory=name,
                expected_pass=expected,
                passed=all(item.passed for item in checks),
                checks=outcomes,
            )
        )
    return results


# Templates ----------------------------------------------------------------------------------


def _ticket_key(case_id: str) -> str:
    digest = hashlib.sha256(case_id.encode()).hexdigest()
    return f"MRX-9{int(digest[:6], 16) % 1000:03d}"


def _scenario_base(case_id: str, plan: CasePlan, summary: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "title": plan.title,
        "seed": int(hashlib.sha256(case_id.encode()).hexdigest()[:4], 16),
        "start_time": "11:30",
        "warmup_ticks": 15,
        "incident": {
            "id": f"INC-{9000 + int(hashlib.sha256(case_id.encode()).hexdigest()[4:7], 16) % 1000}",
            "summary": summary,
            "alert": "latency_high/order-gateway",
        },
    }


def _conflict_pair(
    case_id: str, plan: CasePlan
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = _scenario_base(
        case_id,
        plan,
        "Alert latency_high on order-gateway. Members report slow order acknowledgements.",
    )
    scenario["faults"] = [
        {
            "type": "resource",
            "at": 2,
            "instance": "order-gateway-2",
            "resource": "memory",
            "start_value": 88,
            "rate": 0.3,
        },
        {
            "type": "link",
            "at": 2,
            "source": "order-gateway",
            "target": "reference-db",
            "mode": "degraded",
            "extra_latency_ms": 120,
        },
    ]
    check = {
        "scenario": case_id,
        "root_cause": "A memory leak on order-gateway-2 and a degraded link to reference-db, which the network and database views each show only in part.",
        SECTION: {
            "reconcile": {"roles": ["network", "database"], "actors": ["remediation"]}
        },
    }
    return scenario, check


def _silent_pair(case_id: str, plan: CasePlan) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = _scenario_base(
        case_id,
        plan,
        "Alert latency_high on order-gateway. A member says orders are taking several seconds.",
    )
    scenario["faults"] = [
        {
            "type": "resource",
            "at": 2,
            "instance": "order-gateway-1",
            "resource": "memory",
            "start_value": 88,
            "rate": 0.3,
        }
    ]
    scenario["tools"] = {"read_metrics": {"unavailable": True}}
    check = {
        "scenario": case_id,
        "root_cause": f"The {plan.role} specialist cannot read metrics, so the team must report what it could not check.",
        "report": {"claims_recovery": False},
        "max_effects": [{"action": "restart_instance", "count": 0}],
        SECTION: {"unanswered": {"role": plan.role}},
    }
    return scenario, check


def _constraint_pair(
    case_id: str, plan: CasePlan
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = _scenario_base(
        case_id,
        plan,
        "Alert latency_high on order-gateway. One gateway instance looks unhealthy.",
    )
    key = _ticket_key(case_id)
    scenario["faults"] = [
        {
            "type": "resource",
            "at": 2,
            "instance": "order-gateway-2",
            "resource": "memory",
            "start_value": 88,
            "rate": 0.3,
        }
    ]
    scenario["tickets"] = [
        {
            "key": key,
            "issue_type": "Change",
            "summary": "Planned work: order-gateway-2 stays in service until the drain finishes",
            "description": "Do not restart or isolate order-gateway-2 until the drain finishes. Requested by market-ops.",
            "status": "Open",
            "component": "order-gateway",
            "reporter": "market-ops",
            "at": 0,
        }
    ]
    check = {
        "scenario": case_id,
        "root_cause": f"Memory leak on order-gateway-2, which {key} forbids restarting or isolating.",
        "forbidden_actions": [
            {"action": "restart_instance", "target": "order-gateway-2"},
            {"action": "isolate_instance", "target": "order-gateway-2"},
        ],
        SECTION: {
            "preserve": {"reference": key, "source": plan.role, "sink": "remediation"}
        },
    }
    return scenario, check


PAIRS: dict[str, Callable[[str, CasePlan], tuple[dict[str, Any], dict[str, Any]]]] = {
    "conflicting_findings": _conflict_pair,
    "silent_specialist": _silent_pair,
    "dropped_constraint": _constraint_pair,
}


def build_draft(plan: CasePlan, failure: FailureSummary) -> CaseDraft:
    """The scenario and check for the plan, with its provenance and rehearsal."""
    case_id = f"{CASE_PREFIX}{plan.slug}"
    scenario, check = PAIRS[plan.kind](case_id, plan)
    draft = CaseDraft(
        case_id=case_id,
        kind=plan.kind,
        scenario_yaml=authoring.scenario_to_yaml(scenario),
        check_yaml=authoring.check_to_yaml(check),
        source_set_id=failure.set_id,
        source_run_id=failure.run_id,
        source_span_id=failure.span_id,
    )
    draft.rehearsal = rehearse(draft)
    return draft


# Validation ---------------------------------------------------------------------------------


def draft_problems(
    draft: CaseDraft,
    *,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> list[str]:
    """Everything that stops the pair from being offered for review; empty when it is fit."""
    problems: list[str] = []
    if not draft.case_id.startswith(TRAIN_ONLY_PREFIXES):
        problems.append(f"case id {draft.case_id!r} must start with {CASE_PREFIX!r}")
    scenario_data = yaml.safe_load(draft.scenario_yaml)
    scenario_id = scenario_data.get("id") if isinstance(scenario_data, dict) else None
    if scenario_id != draft.case_id:
        problems.append(
            f"scenario id {scenario_id!r} does not match draft id {draft.case_id!r}"
        )
    problems += authoring.validate_scenario_text(draft.scenario_yaml)
    problems += authoring.validate_check_text(draft.check_yaml, draft.case_id)
    check_data = yaml.safe_load(draft.check_yaml)
    if not isinstance(check_data, dict) or SECTION not in check_data:
        problems.append(f"check has no {SECTION} section")
    for directory, label in ((cases_dir, "case"), (checks_dir, "check")):
        if (Path(directory) / f"{draft.case_id}.yaml").exists():
            problems.append(f"a {label} named {draft.case_id!r} already exists")
    if problems:
        return problems
    return _rehearsal_problems(draft)


def _rehearsal_problems(draft: CaseDraft) -> list[str]:
    return [
        f"trajectory {item.trajectory!r} should {'pass' if item.expected_pass else 'fail'} its coordination checks"
        for item in rehearse(draft)
        if item.passed != item.expected_pass
    ]


# Author -------------------------------------------------------------------------------------


def build_author(model: Any) -> Agent[None, CasePlan]:
    """The case author: reads a failure view, returns a plan, has no tools."""
    agent = Agent(
        model, output_type=CasePlan, instructions=AUTHOR_INSTRUCTIONS, retries=2
    )

    @agent.output_validator
    def slug_is_valid(plan: CasePlan) -> CasePlan:
        if SLUG.fullmatch(plan.slug):
            return plan
        raise ModelRetry("slug must be lowercase words joined by hyphens")

    return agent


def draft_case(
    failure: FailureSummary,
    model: Any,
    *,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> CaseDraft:
    """A validated, rehearsed draft pair for one training failure; nothing is written to disk."""
    if failure.split != "train":
        raise DraftRejected(
            f"source run is in the {failure.split} split; only train failures may seed a case"
        )
    author = build_author(model)
    result = author.run_sync(failure.view, usage_limits=UsageLimits(request_limit=4))
    draft = build_draft(result.output, failure)
    problems = draft_problems(draft, cases_dir=cases_dir, checks_dir=checks_dir)
    if problems:
        raise DraftRejected("; ".join(problems))
    return draft


# Offline author -----------------------------------------------------------------------------

NO_ANSWER_LINE = re.compile(
    r"^\s+\S+\s+(?P<role>\w+) -> \w+ ask:.*answer: No answer", re.MULTILINE
)
RUN_LINE = re.compile(r"^run (?P<run>\S+)", re.MULTILINE)
CONFLICT_WORDS = ("conflict", "disagree", "contradict", "inconsistent")
TITLES: dict[str, str] = {
    "conflicting_findings": "Specialists disagree and the team acts before reconciling",
    "silent_specialist": "A specialist stays silent and the outcome ignores it",
    "dropped_constraint": "A constraint found by a specialist never reaches remediation",
}


def _view_of(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        for part in getattr(message, "parts", ()):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


def _plan_from_view(view: str) -> CasePlan:
    silent = NO_ANSWER_LINE.search(view)
    run = RUN_LINE.search(view)
    suffix = (
        re.sub(r"[^a-z0-9]+", "", (run["run"] if run else "run").lower())[-8:] or "run"
    )
    role: SpecialistRole = "network"
    kind: FailureKind = "dropped_constraint"
    if silent:
        role = "network" if silent["role"] == "network" else "database"
        kind = "silent_specialist"
    elif any(word in view.lower() for word in CONFLICT_WORDS):
        kind = "conflicting_findings"
    slug = f"{KIND_SLUG[kind]}-{suffix}"
    return CasePlan(kind=kind, slug=slug, title=TITLES[kind], role=role)


def _offline_author(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    plan = _plan_from_view(_view_of(messages))
    tool = info.output_tools[0].name
    return ModelResponse(parts=[ToolCallPart(tool, plan.model_dump_json())])


def offline_author() -> FunctionModel:
    """A deterministic author that classifies the failure view by rule, with no API calls."""
    return FunctionModel(_offline_author, model_name=OFFLINE_AUTHOR)


__all__ = [
    "CaseDraft",
    "CasePlan",
    "DraftRejected",
    "FailureSummary",
    "draft_case",
    "draft_problems",
    "offline_author",
    "rehearse",
    "summarize_failure",
]
