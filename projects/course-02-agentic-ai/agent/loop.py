"""The version loop over one agent: baseline, critic, proposer, candidate, trusted decision.

One call to `run_iteration` makes one candidate attempt. The critic reads training failures only;
the proposer gets the validated blames of the chosen role, that role's current version file and
a summary of earlier attempts. Validation outcomes never leave this module's trusted code, and
the test split is only run by `run_test`, which calls neither agent.

Nothing here edits `harnesses/team.yaml`. A kept version is a new file under
`harnesses/versions/<role>/`, and a human pins it.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import pieces
from agent.decision import compare_cases, decide
from agent.models import Attempt, Blame, Decision, Proposal
from agent.suite import (
    HARNESS_NAME,
    Compare,
    CompareRequest,
    load_staged_fingerprint,
    next_version,
    raise_if_budget_exhausted,
    staged_team,
    team_pins,
    trusted_facts,
    write_version_file,
)
from agent.versions import ROLES, Role, RoleVersion, TeamVersion, load_team
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from app import commands
from app.core.case_splits import CaseSplits
from app.core.model_budget import BudgetExhaustedError, ModelBudget
from app.core.results import ResultSet, load_result_set
from app.core.runner import RunRecord
from app.core.team_trace import (
    RoleVerdict,
    TeamTrace,
    TrustedFacts,
    check_roles,
    critic_view,
    load_spans,
    project_trace,
)
from app.paths import HARNESSES_DIR, RESULTS_DIR

AGENT_DIR = Path(__file__).resolve().parent
LINEAGE_FILE = HARNESSES_DIR / "versions" / "lineage.jsonl"
DEFAULT_MAX_CRITIQUES = 6
FactsFor = Callable[[RunRecord], TrustedFacts]


@dataclass
class LoopConfig:
    role: Role
    reps: int
    splits: CaseSplits
    # Models are already resolved: the offline marker or stubs, or live models behind one budget.
    critic_model: Any
    proposer_model: Any
    model_names: dict[str, str]
    harnesses_dir: Path = HARNESSES_DIR
    results_dir: Path = RESULTS_DIR
    lineage_file: Path = LINEAGE_FILE
    facts_for: FactsFor = trusted_facts
    max_critiques: int = DEFAULT_MAX_CRITIQUES
    invocation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])

    @property
    def team_file(self) -> Path:
        return self.harnesses_dir / "team.yaml"

    @property
    def versions_dir(self) -> Path:
        return self.harnesses_dir / "versions"


# Memory ----------------------------------------------------------------------------------------


def snapshot_compare(
    model: Any, *, memory_snapshot: Path, results_dir: Path, max_workers: int = 4
) -> Compare:
    """The workbench compare with one memory snapshot: every run copies it and learns nothing.

    The arms of a comparison start from the same memory, so a candidate cannot win by what a
    baseline run wrote down.
    """

    def compare(request: CompareRequest) -> ResultSet:
        outcome = commands.compare(
            [HARNESS_NAME],
            request.case_ids,
            reps=request.reps,
            model=model,
            max_workers=max_workers,
            save_label=request.label,
            memory_snapshot=memory_snapshot,
            harnesses_dir=request.harnesses_dir,
            results_dir=results_dir,
        )
        saved = load_result_set(outcome["result_set"], results_dir=results_dir)
        raise_if_budget_exhausted(saved.runs)
        return saved

    return compare


# Lineage ---------------------------------------------------------------------------------------


def append_lineage(path: Path, attempt: Attempt) -> None:
    """Append one line; a single O_APPEND write keeps concurrent loops from interleaving."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(attempt.model_dump(mode="json"), ensure_ascii=False) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)


def load_lineage(path: Path) -> list[Attempt]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Attempt.model_validate_json(line) for line in lines if line.strip()]


def pin_instruction(
    attempt: Attempt, harnesses_dir: Path = HARNESSES_DIR
) -> str | None:
    """What a human does to make an adopted version the team's: loops never edit team.yaml."""
    if attempt.adopted_file is None or attempt.candidate_version is None:
        return None
    team_file = harnesses_dir / "team.yaml"
    role, was, now = attempt.role, attempt.parent_version, attempt.candidate_version
    return (
        f"to pin it, set `{role}: {now}` (was {was}) under versions in {team_file}, "
        f"for example: sed -i 's/^  {role}: {was}$/  {role}: {now}/' {team_file}"
    )


# Critic ----------------------------------------------------------------------------------------


def _blame_run(model: Any, trace: TeamTrace, verdicts: Sequence[RoleVerdict]) -> Blame:
    # critic.py imports `models`, which lives beside it, so its folder must be importable.
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    critic = importlib.import_module("agent.critic")
    return critic.blame_run(model, trace, verdicts)


def _project(record: RunRecord, results_dir: Path) -> TeamTrace:
    if not record.spans_file:
        raise LookupError(f"run {record.run_id} has no saved spans")
    return project_trace(load_spans(results_dir / record.spans_file))


def _critique_sample(records: Sequence[RunRecord], limit: int) -> list[RunRecord]:
    """One failed run per case with saved spans, in case order, at most `limit`."""
    chosen: dict[str, RunRecord] = {}
    for record in sorted(records, key=lambda item: (item.case_id, item.run_id)):
        if record.outcome in ("failed", "errored") and record.spans_file:
            chosen.setdefault(record.case_id, record)
    return list(chosen.values())[:limit]


def collect_blames(
    config: LoopConfig, failures: Sequence[RunRecord]
) -> list[tuple[str, Blame]]:
    """Validated blames of the chosen role on training failures; the critic needs no tools."""
    blames: list[tuple[str, Blame]] = []
    for record in _critique_sample(failures, config.max_critiques):
        trace = _project(record, config.results_dir)
        verdicts = check_roles(trace, config.facts_for(record))
        try:
            blame = _blame_run(config.critic_model, trace, verdicts)
        except (UnexpectedModelBehavior, UsageLimitExceeded):
            # A critic that never cites a real span gives no evidence; it must not stop the loop.
            continue
        if blame.role == config.role:
            blames.append((record.case_id, blame))
    return blames


def review_run(
    record: RunRecord,
    *,
    critic_model: Any,
    results_dir: Path = RESULTS_DIR,
    facts_for: FactsFor = trusted_facts,
) -> dict[str, Any]:
    """The per-agent view of one saved run, its role checks and the critic's validated blame."""
    trace = _project(record, results_dir)
    verdicts = check_roles(trace, facts_for(record))
    blame: Blame | None = None
    failure = ""
    try:
        blame = _blame_run(critic_model, trace, verdicts)
    except (UnexpectedModelBehavior, UsageLimitExceeded) as unusable:
        failure = str(unusable)
    return {
        "run_id": record.run_id,
        "case_id": record.case_id,
        "outcome": record.outcome,
        "view": critic_view(trace, verdicts),
        "role_checks": [verdict.model_dump() for verdict in verdicts],
        "blame": blame.model_dump() if blame else None,
        "blame_error": failure,
    }


# The iteration ---------------------------------------------------------------------------------


class _Iteration:
    """State of one attempt, kept so a budget stop can still report what was saved."""

    def __init__(self, config: LoopConfig, compare: Compare, budget: ModelBudget):
        self.config = config
        self.compare = compare
        self.budget = budget
        self.baseline = load_team(config.team_file)
        self.parent = self.baseline.roles[config.role]
        self.sets: dict[str, str] = {}
        self.blames_used = 0
        self.change: Proposal | None = None
        self.candidate: RoleVersion | None = None
        self.candidate_team: TeamVersion | None = None

    def _case_ids(self, split: str) -> list[str]:
        return list(getattr(self.config.splits, split))

    def _run(self, arm: str, split: str, harnesses_dir: Path) -> ResultSet:
        if self.budget.remaining_usd <= 0:
            raise BudgetExhaustedError("the budget is spent")
        request = CompareRequest(
            label=f"improve-{self.config.role}-{self.config.invocation_id}-{arm}-{split}",
            arm=arm,  # type: ignore[arg-type]
            split=split,  # type: ignore[arg-type]
            case_ids=self._case_ids(split),
            reps=self.config.reps,
            harnesses_dir=harnesses_dir,
        )
        saved = self.compare(request)
        self.sets[f"{arm}_{split}"] = saved.set_id
        return saved

    def _earlier(self) -> list[str]:
        lines = [
            pieces.attempt_summary(attempt)
            for attempt in load_lineage(self.config.lineage_file)
            if attempt.role == self.config.role
        ]
        return [line for line in lines if line]

    def attempt_for(self, status: str, detail: str = "") -> Attempt:
        config = self.config
        return Attempt(
            invocation_id=config.invocation_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            role=config.role,
            status=status,  # type: ignore[arg-type]
            parent_version=self.parent.version,
            candidate_version=self.candidate.version if self.candidate else None,
            change=self.change,
            detail=detail,
            sets=dict(self.sets),
            splits_fingerprint=config.splits.fingerprint,
            baseline_team=self.baseline.fingerprint,
            candidate_team=self.candidate_team.fingerprint
            if self.candidate_team
            else None,
            baseline_pins=team_pins(self.baseline),
            candidate_pins=team_pins(self.candidate_team)
            if self.candidate_team
            else {},
            reps=config.reps,
            models=config.model_names,
            blames_used=self.blames_used,
            spent_usd=str(self.budget.spent_usd),
        )

    def run(self) -> Attempt:
        config = self.config
        baseline_dir = config.harnesses_dir
        baseline_train = self._run("baseline", "train", baseline_dir)
        baseline_valid = self._run("baseline", "valid", baseline_dir)

        failures = [run for run in baseline_train.runs if run.outcome != "passed"]
        blames = collect_blames(config, failures)
        self.blames_used = len(blames)

        message = pieces.proposer_message(self.parent, blames, self._earlier())
        try:
            self.change = pieces.propose(config.proposer_model, message)
        except (UnexpectedModelBehavior, UsageLimitExceeded) as unusable:
            return self.attempt_for("no_proposal", str(unusable))
        version = next_version(config.versions_dir, config.role)
        try:
            self.candidate = pieces.apply_proposal(
                self.parent, self.change, target=config.role, next_version=version
            )
        except pieces.ProposalRejected as rejection:
            return self.attempt_for("invalid_proposal", str(rejection))

        self.candidate_team = load_team(config.team_file, override=self.candidate)
        with staged_team(config.harnesses_dir, override=self.candidate) as staged:
            if load_staged_fingerprint(staged) != self.candidate_team.fingerprint:
                raise RuntimeError("the staged candidate differs from the resolved one")
            candidate_train = self._run("candidate", "train", staged)
            candidate_valid = self._run("candidate", "valid", staged)

        decision = decide(
            compare_cases(
                config.splits.train,
                config.reps,
                baseline_train.runs,
                candidate_train.runs,
            ),
            compare_cases(
                config.splits.valid,
                config.reps,
                baseline_valid.runs,
                candidate_valid.runs,
            ),
        )
        return self._conclude(decision)

    def _conclude(self, decision: Decision) -> Attempt:
        attempt = self.attempt_for("decided")
        attempt.decision = decision
        if not decision.adopt or self.candidate is None:
            return attempt
        try:
            written = write_version_file(self.config.versions_dir, self.candidate)
        except FileExistsError:
            attempt.decision = decision.model_copy(
                update={
                    "adopt": False,
                    "reasons": [*decision.reasons, "the version file already exists"],
                }
            )
            return attempt
        attempt.adopted_file = str(written)
        return attempt


def run_iteration(config: LoopConfig, compare: Compare, budget: ModelBudget) -> Attempt:
    """One candidate attempt for `config.role`; the attempt is also appended to the lineage."""
    if config.role in pieces.UNPROPOSABLE_ROLES or config.role not in ROLES:
        raise ValueError(f"the {config.role} role cannot be a target")
    iteration = _Iteration(config, compare, budget)
    try:
        attempt = iteration.run()
    except BudgetExhaustedError as exhausted:
        attempt = iteration.attempt_for("budget_exhausted", str(exhausted))
    append_lineage(config.lineage_file, attempt)
    return attempt


# Final test ------------------------------------------------------------------------------------


def resolve_team_reference(
    reference: str, harnesses_dir: Path, lineage_file: Path
) -> tuple[Path | None, dict[Role, str] | None, str]:
    """(team file, pins, fingerprint) for a team.yaml path or a team fingerprint."""
    path = Path(reference)
    if path.is_file():
        team = load_team(path)
        return path, None, team.fingerprint
    current = load_team(harnesses_dir / "team.yaml")
    if current.fingerprint.startswith(reference):
        return None, None, current.fingerprint
    for attempt in reversed(load_lineage(lineage_file)):
        for fingerprint, pins in (
            (attempt.candidate_team, attempt.candidate_pins),
            (attempt.baseline_team, attempt.baseline_pins),
        ):
            if fingerprint and fingerprint.startswith(reference):
                return None, dict(pins), fingerprint  # type: ignore[arg-type]
    raise LookupError(f"no team file or known team fingerprint {reference!r}")


def run_test(
    reference: str,
    *,
    splits: CaseSplits,
    reps: int,
    compare: Compare,
    harnesses_dir: Path = HARNESSES_DIR,
    lineage_file: Path = LINEAGE_FILE,
) -> dict[str, Any]:
    """Run the test split for one sealed team. No critic or proposer is involved."""
    team_file, pins, fingerprint = resolve_team_reference(
        reference, harnesses_dir, lineage_file
    )
    with staged_team(harnesses_dir, team_file=team_file, pins=pins) as staged:
        try:
            staged_fingerprint = load_staged_fingerprint(staged)
        except FileNotFoundError as missing:
            raise LookupError(
                f"team {fingerprint} needs a version file that was never kept ({missing.filename})"
            ) from missing
        if staged_fingerprint != fingerprint:
            raise LookupError(
                f"team {fingerprint} cannot be rebuilt from the kept versions"
            )
        request = CompareRequest(
            label=f"improve-test-{fingerprint}-{uuid.uuid4().hex[:4]}",
            arm="candidate",
            split="test",
            case_ids=list(splits.test),
            reps=reps,
            harnesses_dir=staged,
        )
        saved = compare(request)
    passed = sum(1 for run in saved.runs if run.outcome == "passed")
    return {
        "team": fingerprint,
        "result_set": saved.set_id,
        "splits_fingerprint": splits.fingerprint,
        "runs": len(saved.runs),
        "passed": passed,
        "pass_rate": passed / len(saved.runs) if saved.runs else None,
    }


__all__ = [
    "LoopConfig",
    "append_lineage",
    "collect_blames",
    "load_lineage",
    "pin_instruction",
    "review_run",
    "run_iteration",
    "run_test",
    "snapshot_compare",
]
