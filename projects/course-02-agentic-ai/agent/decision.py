"""Whether a candidate team replaces the baseline.

The rule runs in trusted code on saved run records. Only the full-team workbench verdict counts:
a run passes when it completed and the Meridian evaluator passed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agent.models import Decision

from app.core.runner import RunRecord


@dataclass(frozen=True)
class ArmRuns:
    passes: int
    runs: int
    # Runs that errored or were never evaluated: they prove nothing either way.
    incomplete: int


@dataclass(frozen=True)
class CaseComparison:
    case_id: str
    expected_runs: int
    baseline: ArmRuns
    candidate: ArmRuns


def _arm(records: Sequence[RunRecord]) -> ArmRuns:
    passes = sum(1 for record in records if record.outcome == "passed")
    incomplete = sum(
        1 for record in records if record.outcome in ("errored", "not_evaluated")
    )
    return ArmRuns(passes=passes, runs=len(records), incomplete=incomplete)


def compare_cases(
    case_ids: Iterable[str],
    reps: int,
    baseline: Iterable[RunRecord],
    candidate: Iterable[RunRecord],
) -> list[CaseComparison]:
    """One comparison per case; a case with no runs in an arm shows up as missing runs."""
    by_arm: dict[str, dict[str, list[RunRecord]]] = {
        "baseline": defaultdict(list),
        "candidate": defaultdict(list),
    }
    for record in baseline:
        by_arm["baseline"][record.case_id].append(record)
    for record in candidate:
        by_arm["candidate"][record.case_id].append(record)
    return [
        CaseComparison(
            case_id=case_id,
            expected_runs=reps,
            baseline=_arm(by_arm["baseline"][case_id]),
            candidate=_arm(by_arm["candidate"][case_id]),
        )
        for case_id in sorted(set(case_ids))
    ]


def _rate(arms: Iterable[ArmRuns]) -> float | None:
    chosen = list(arms)
    runs = sum(arm.runs for arm in chosen)
    if runs == 0:
        return None
    return sum(arm.passes for arm in chosen) / runs


def _blockers(comparisons: Sequence[CaseComparison]) -> list[str]:
    blockers: list[str] = []
    for comparison in comparisons:
        for name, arm in (
            ("baseline", comparison.baseline),
            ("candidate", comparison.candidate),
        ):
            if arm.runs != comparison.expected_runs:
                blockers.append(
                    f"{comparison.case_id}: {name} has {arm.runs} of "
                    f"{comparison.expected_runs} runs"
                )
            if arm.incomplete:
                blockers.append(
                    f"{comparison.case_id}: {name} has {arm.incomplete} errored or "
                    "unevaluated runs"
                )
    return blockers


def decide(
    train: Sequence[CaseComparison], valid: Sequence[CaseComparison]
) -> Decision:
    """Adopt only when the training pass rate rises and no validation case passes less often.

    Missing, errored or unevaluated runs in either arm block adoption.
    """
    if not train or not valid:
        return Decision(adopt=False, reasons=["train and valid both need cases"])
    blockers = _blockers([*train, *valid])
    train_baseline = _rate(case.baseline for case in train)
    train_candidate = _rate(case.candidate for case in train)
    regressed = [
        case.case_id for case in valid if case.candidate.passes < case.baseline.passes
    ]
    if blockers:
        return Decision(
            adopt=False,
            reasons=[f"incomplete evidence: {blocker}" for blocker in blockers],
            train_baseline_rate=train_baseline,
            train_candidate_rate=train_candidate,
            regressed_cases=regressed,
        )
    reasons: list[str] = []
    if train_baseline is None or train_candidate is None:
        reasons.append("no training runs")
    elif train_candidate <= train_baseline:
        reasons.append(
            f"training pass rate did not rise ({train_baseline:.0%} to {train_candidate:.0%})"
        )
    if regressed:
        reasons.append(f"validation regressed on {', '.join(regressed)}")
    if reasons:
        return Decision(
            adopt=False,
            reasons=reasons,
            train_baseline_rate=train_baseline,
            train_candidate_rate=train_candidate,
            regressed_cases=regressed,
        )
    return Decision(
        adopt=True,
        reasons=[
            (
                f"training pass rate rose {train_baseline:.0%} to {train_candidate:.0%}, "
                "no validation case regressed"
            )
        ],
        train_baseline_rate=train_baseline,
        train_candidate_rate=train_candidate,
    )
