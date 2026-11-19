"""Coordination checks: three fixed predicates over the team's handoffs.

A check file may carry a `coordination:` section. Each key turns one predicate on:

    coordination:
      reconcile: {roles: [network, database], actors: [remediation]}
      unanswered: {role: database}
      preserve: {reference: MRX-9301, source: network, sink: remediation}

The predicates read the handoffs the team recorded (`agent.team_tools.Handoff`), never an agent's
own claim about them. Without handoffs the section cannot be judged, so it fails explicitly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from agent.versions import Role
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from meridian.evaluate import Check

if TYPE_CHECKING:
    from agent.team_tools import Handoff

SECTION = "coordination"
# Words that show an orchestrator told the next role about a disagreement or a missing answer.
RECONCILE_TERMS = ("conflict", "disagree", "contradict", "reconcil", "inconsistent")
ACCOUNT_TERMS = ("no answer", "unanswered", "did not answer", "no response", "silent")


class ReconcileSpec(BaseModel):
    """Two specialists whose findings differ; an actor must not act until the team reconciles them."""

    model_config = ConfigDict(extra="forbid")

    roles: list[Role] = Field(min_length=2, max_length=2)
    actors: list[Role] = Field(default_factory=lambda: ["remediation"], min_length=1)

    @model_validator(mode="after")
    def _distinct_specialists(self) -> ReconcileSpec:
        if len(set(self.roles)) != 2 or "orchestrator" in self.roles:
            raise ValueError("roles must be two different specialists")
        return self


class UnansweredSpec(BaseModel):
    """A specialist that will not answer; the rest of the run must account for that."""

    model_config = ConfigDict(extra="forbid")

    role: Role

    @model_validator(mode="after")
    def _specialist(self) -> UnansweredSpec:
        if self.role == "orchestrator":
            raise ValueError("role must be a specialist")
        return self


class PreserveSpec(BaseModel):
    """A reference (ticket, change id or evidence ref) one role finds and another must receive."""

    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1)
    source: Role
    sink: Role = "remediation"

    @model_validator(mode="after")
    def _distinct_roles(self) -> PreserveSpec:
        if self.source in ("orchestrator", self.sink):
            raise ValueError("source must be a specialist other than sink")
        return self


class CoordinationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconcile: ReconcileSpec | None = None
    unanswered: UnansweredSpec | None = None
    preserve: PreserveSpec | None = None

    @model_validator(mode="after")
    def _one_predicate(self) -> CoordinationSpec:
        if self.reconcile or self.unanswered or self.preserve:
            return self
        raise ValueError("name at least one of reconcile, unanswered, preserve")


def _describe(item: Any) -> str:
    where = ".".join([SECTION, *(str(part) for part in item["loc"])])
    return f"{where}: {item['msg']}"


def validate_coordination(spec: Any) -> list[str]:
    """Why the `coordination:` section is malformed; empty when it is well formed."""
    if not isinstance(spec, dict):
        return [f"{SECTION} must be a mapping, got {type(spec).__name__}"]
    try:
        CoordinationSpec.model_validate(spec)
    except ValidationError as error:
        return [_describe(item) for item in error.errors()]
    return []


def _text(handoff: Handoff) -> str:
    payload = json.dumps(handoff.payload, sort_keys=True, ensure_ascii=False)
    return f"{payload} {' '.join(handoff.evidence_refs)}".lower()


def _first_index(handoffs: Sequence[Handoff], matches: Any) -> int | None:
    for index, handoff in enumerate(handoffs):
        if matches(handoff):
            return index
    return None


def _reconciled_before_action(
    handoffs: Sequence[Handoff], spec: ReconcileSpec
) -> Check:
    name = f"coordination: {' and '.join(spec.roles)} conflict reconciled before action"
    answered = [
        _first_index(
            handoffs,
            lambda item, role=role: item.sender == role and item.kind == "result",
        )
        for role in spec.roles
    ]
    if None in answered:
        return Check(
            name, False, "both specialists did not answer, so no conflict was seen"
        )
    ready = max(index for index in answered if index is not None)
    action = _first_index(
        handoffs,
        lambda item: item.kind == "request" and item.recipient in spec.actors,
    )
    if action is None:
        return Check(name, True, "no action was requested")
    if action < ready:
        return Check(
            name, False, f"{handoffs[action].id} asked for action before both findings"
        )
    follow_up = _first_index(
        handoffs[ready + 1 : action],
        lambda item: item.kind == "request" and item.recipient in spec.roles,
    )
    mentioned = any(term in _text(handoffs[action]) for term in RECONCILE_TERMS)
    if follow_up is not None:
        return Check(
            name, True, "a follow-up request went to a specialist before the action"
        )
    if mentioned:
        return Check(name, True, f"{handoffs[action].id} names the disagreement")
    return Check(
        name, False, f"{handoffs[action].id} asked for action with the conflict open"
    )


def _unanswered_accounted(handoffs: Sequence[Handoff], spec: UnansweredSpec) -> Check:
    name = f"coordination: {spec.role} no-answer accounted for"
    silent = _first_index(
        handoffs, lambda item: item.sender == spec.role and item.kind == "no_answer"
    )
    if silent is None:
        return Check(name, False, f"{spec.role} never recorded a no-answer")
    for handoff in handoffs[silent + 1 :]:
        if handoff.kind != "request" or handoff.recipient == spec.role:
            continue
        text = _text(handoff)
        if spec.role in text or any(term in text for term in ACCOUNT_TERMS):
            return Check(name, True, f"{handoff.id} carries the gap forward")
    return Check(
        name, False, f"nothing after {handoffs[silent].id} mentions the missing answer"
    )


def _reference_preserved(handoffs: Sequence[Handoff], spec: PreserveSpec) -> Check:
    name = f"coordination: {spec.reference} preserved from {spec.source} to {spec.sink}"
    reference = spec.reference.lower()
    found = _first_index(
        handoffs, lambda item: item.sender == spec.source and reference in _text(item)
    )
    if found is None:
        return Check(name, False, f"{spec.source} never surfaced {spec.reference}")
    for handoff in handoffs[found + 1 :]:
        if (
            handoff.kind == "request"
            and handoff.recipient == spec.sink
            and reference in _text(handoff)
        ):
            return Check(name, True, f"{handoff.id} still carries it")
    return Check(
        name, False, f"no request to {spec.sink} after {handoffs[found].id} carries it"
    )


def evaluate_coordination(spec: Any, handoffs: Sequence[Handoff] | None) -> list[Check]:
    """One check per predicate in the section, judged on the recorded handoffs."""
    problems = validate_coordination(spec)
    if problems:
        return [Check("coordination: section is valid", False, "; ".join(problems))]
    if not handoffs:
        return [
            Check(
                "coordination: team handoff evidence",
                False,
                "no team handoffs were recorded; run this case with a team harness",
            )
        ]
    parsed = CoordinationSpec.model_validate(spec)
    checks: list[Check] = []
    if parsed.reconcile:
        checks.append(_reconciled_before_action(handoffs, parsed.reconcile))
    if parsed.unanswered:
        checks.append(_unanswered_accounted(handoffs, parsed.unanswered))
    if parsed.preserve:
        checks.append(_reference_preserved(handoffs, parsed.preserve))
    return checks
