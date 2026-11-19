"""The typed contracts of the version loop: what the critic and the proposer return, and what the
trusted code decides and records."""

from __future__ import annotations

from typing import Annotated, Literal

from agent.versions import Role
from pydantic import BaseModel, Field

from app.core.team_trace import Blame

__all__ = [
    "Attempt",
    "Blame",
    "Decision",
    "EditInstructions",
    "EditMaxRequests",
    "EditMaxToolCalls",
    "EditTools",
    "EditVerifyRecovery",
    "FieldEdit",
    "Proposal",
]


class EditInstructions(BaseModel):
    field: Literal["instructions"]
    value: str = Field(description="The complete new instructions of the agent.")


class EditTools(BaseModel):
    field: Literal["tools"]
    value: list[str] = Field(description="The tools the agent keeps, from its catalog.")


class EditMaxRequests(BaseModel):
    field: Literal["max_requests"]
    value: int


class EditMaxToolCalls(BaseModel):
    field: Literal["max_tool_calls"]
    value: int


class EditVerifyRecovery(BaseModel):
    field: Literal["verify_recovery"]
    value: bool = Field(
        description="Remediation only: report 'resolved' after healthy readings."
    )


FieldEdit = Annotated[
    EditInstructions
    | EditTools
    | EditMaxRequests
    | EditMaxToolCalls
    | EditVerifyRecovery,
    Field(discriminator="field"),
]


class Proposal(BaseModel):
    """What the proposer returns: ONE field edit to ONE agent's version file."""

    role: Role = Field(description="The agent whose version the edit applies to.")
    edit: FieldEdit
    rationale: str = Field(description="Why this edit addresses the blames, briefly.")

    @property
    def summary(self) -> str:
        value = self.edit.value
        text = value if isinstance(value, str) else str(value)
        shortened = " ".join(text.split())[:80]
        return f"{self.role}.{self.edit.field} = {shortened}"


class Decision(BaseModel):
    """The trusted verdict on one candidate."""

    adopt: bool
    reasons: list[str]
    train_baseline_rate: float | None = None
    train_candidate_rate: float | None = None
    # Validation cases where the candidate passes fewer runs than the baseline.
    regressed_cases: list[str] = Field(default_factory=list)


class Attempt(BaseModel):
    """One iteration of the loop, as written to the lineage file."""

    invocation_id: str
    created_at: str
    role: Role
    status: Literal["decided", "invalid_proposal", "budget_exhausted", "no_proposal"]
    parent_version: str
    candidate_version: str | None = None
    change: Proposal | None = None
    decision: Decision | None = None
    detail: str = ""
    # Saved result set ids: baseline_train, baseline_valid, candidate_train, candidate_valid.
    sets: dict[str, str] = Field(default_factory=dict)
    splits_fingerprint: str
    baseline_team: str
    candidate_team: str | None = None
    # The version pinned for each role in the baseline and the candidate team.
    baseline_pins: dict[str, str] = Field(default_factory=dict)
    candidate_pins: dict[str, str] = Field(default_factory=dict)
    reps: int
    models: dict[str, str] = Field(default_factory=dict)
    blames_used: int = 0
    spent_usd: str = "0"
    adopted_file: str | None = None
