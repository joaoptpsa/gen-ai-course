"""The workbench's command layer: one handler per CLI subcommand.

The CLI parses arguments and prints what a handler returns; the GUI calls the same
handlers in-process. Every handler returns JSON-serialisable data and raises
LookupError, ValueError or FileExistsError with a readable message on bad input.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml

from app.core import authoring, catalog, explorer, requirements, results, runner
from app.paths import (
    CASES_DIR,
    CHECKS_DIR,
    HARNESSES_DIR,
    REPO_ROOT,
    REQUIREMENTS_FILE,
    RESULTS_DIR,
    SESSIONS_DIR,
)
from meridian.agent_runtime import default_model

Progress = Callable[[int, int, dict[str, Any]], None]


# Cases -------------------------------------------------------------------------------


def cases_list(
    *, cases_dir: Path = CASES_DIR, checks_dir: Path = CHECKS_DIR
) -> list[dict[str, Any]]:
    return [
        case.to_dict()
        for case in catalog.list_cases(cases_dir=cases_dir, checks_dir=checks_dir)
    ]


def cases_show(
    case_id: str, *, cases_dir: Path = CASES_DIR, checks_dir: Path = CHECKS_DIR
) -> dict[str, Any]:
    case = catalog.get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    text = catalog.case_text(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    return {"case": case.to_dict(), **text}


def cases_validate(scenario_text: str, check_text: str | None = None) -> dict[str, Any]:
    scenario_errors = authoring.validate_scenario_text(scenario_text)
    case_id = _scenario_id(scenario_text) if not scenario_errors else None
    check_errors = (
        authoring.validate_check_text(check_text, case_id or "")
        if check_text is not None and case_id
        else []
    )
    return {
        "valid": not scenario_errors and not check_errors,
        "case_id": case_id,
        "scenario_errors": scenario_errors,
        "check_errors": check_errors,
    }


def cases_write(
    scenario_text: str,
    check_text: str | None,
    *,
    force: bool = False,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> dict[str, Any]:
    return authoring.write_case(
        scenario_text,
        check_text,
        force=force,
        cases_dir=cases_dir,
        checks_dir=checks_dir,
    )


def authoring_schema() -> dict[str, Any]:
    """What a case editor needs to build its forms."""
    return {
        "scenario_keys": sorted(authoring.SCENARIO_KEYS),
        "check_keys": sorted(authoring.CHECK_KEYS),
        "fault_fields": authoring.FAULT_FIELDS,
    }


def _scenario_id(scenario_text: str) -> str:
    return str(yaml.safe_load(scenario_text)["id"])


# Simulator ---------------------------------------------------------------------------


def explore(
    case_id: str,
    ticks: int = 30,
    *,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> dict[str, Any]:
    case = catalog.get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    return explorer.explore(case.path, ticks).to_dict()


# Harnesses and runs ------------------------------------------------------------------


def harnesses_list(
    *, harnesses_dir: Path = HARNESSES_DIR, sessions_dir: Path = SESSIONS_DIR
) -> list[dict[str, Any]]:
    return [
        harness.to_dict()
        for harness in catalog.list_harnesses(
            harnesses_dir=harnesses_dir, sessions_dir=sessions_dir
        )
    ]


def default_model_name() -> str:
    return default_model()


def run(
    harness: str,
    case_id: str,
    *,
    model: Any = None,
    approver: str | None = None,
    max_requests: int = 20,
    save_label: str | None = None,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
    harnesses_dir: Path = HARNESSES_DIR,
    sessions_dir: Path = SESSIONS_DIR,
    results_dir: Path = RESULTS_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Run one harness on one case. `approver` overrides the scenario's approver ("approve_all", "deny_all", "roles:a,b")."""
    harness_info = catalog.get_harness(
        harness, harnesses_dir=harnesses_dir, sessions_dir=sessions_dir
    )
    case = catalog.get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    record = runner.run_case(
        harness_info.path,
        case.path,
        harness_name=harness_info.name,
        model=model,
        approver=runner.parse_approver(approver) if approver else None,
        max_requests=max_requests,
        checks_dir=checks_dir,
        repo_root=repo_root,
    )
    saved = (
        results.save_result_set(
            [record], save_label, results_dir=results_dir, repo_root=repo_root
        )
        if save_label
        else None
    )
    return {"record": record.to_dict(), "result_set": saved.set_id if saved else None}


def compare(
    harnesses: list[str],
    case_ids: list[str] | None = None,
    *,
    reps: int = 1,
    model: Any = None,
    approver: str | None = None,
    max_requests: int = 20,
    max_workers: int = 4,
    baseline: str | None = None,
    by: Literal["harness_case", "case"] = "harness_case",
    save_label: str | None = None,
    on_progress: Progress | None = None,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
    harnesses_dir: Path = HARNESSES_DIR,
    sessions_dir: Path = SESSIONS_DIR,
    results_dir: Path = RESULTS_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Run every harness on every case `reps` times; all cases when `case_ids` is None."""
    if not harnesses:
        raise ValueError("compare needs at least one harness")
    if reps < 1:
        raise ValueError(f"reps must be >= 1, got {reps}")
    chosen_harnesses = [
        catalog.get_harness(
            name, harnesses_dir=harnesses_dir, sessions_dir=sessions_dir
        )
        for name in harnesses
    ]
    all_cases = catalog.list_cases(cases_dir=cases_dir, checks_dir=checks_dir)
    chosen_cases = (
        all_cases
        if case_ids is None
        else [
            catalog.get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
            for case_id in case_ids
        ]
    )
    baseline_runs = (
        results.load_result_set(baseline, results_dir=results_dir).runs
        if baseline
        else None
    )

    def report_progress(done: int, total: int, record: runner.RunRecord) -> None:
        if on_progress:
            on_progress(done, total, record.to_dict())

    records = runner.run_matrix(
        [
            (harness.name, harness.path, case.path)
            for harness in chosen_harnesses
            for case in chosen_cases
        ],
        reps=reps,
        model=model,
        approver=runner.parse_approver(approver) if approver else None,
        max_requests=max_requests,
        max_workers=max_workers,
        on_progress=report_progress,
        checks_dir=checks_dir,
        repo_root=repo_root,
    )
    saved = (
        results.save_result_set(
            records, save_label, results_dir=results_dir, repo_root=repo_root
        )
        if save_label
        else None
    )
    return {
        "summary": results.summarise(records),
        "diff": results.diff_runs(baseline_runs, records, by=by)
        if baseline_runs is not None
        else None,
        "result_set": saved.set_id if saved else None,
        "runs": [record.to_dict() for record in records],
    }


# Saved results -----------------------------------------------------------------------


def results_list(*, results_dir: Path = RESULTS_DIR) -> list[dict[str, Any]]:
    return results.list_result_sets(results_dir=results_dir)


def results_show(set_id: str, *, results_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    result_set = results.load_result_set(set_id, results_dir=results_dir)
    return {**result_set.to_dict(), "summary": results.summarise(result_set.runs)}


def results_diff(
    baseline: str,
    current: str,
    *,
    by: Literal["harness_case", "case"] = "harness_case",
    results_dir: Path = RESULTS_DIR,
) -> list[dict[str, Any]]:
    before = results.load_result_set(baseline, results_dir=results_dir).runs
    after = results.load_result_set(current, results_dir=results_dir).runs
    return results.diff_runs(before, after, by=by)


# Requirements ------------------------------------------------------------------------


def requirements_status(
    *,
    set_id: str | None = None,
    path: Path = REQUIREMENTS_FILE,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, Any]:
    """Status of every requirement against one saved set, or the newest runs of each case when `set_id` is None."""
    deadline, items = requirements.load_requirements(path=path)
    runs = (
        results.load_result_set(set_id, results_dir=results_dir).runs
        if set_id
        else results.latest_runs_by_case(results_dir=results_dir)
    )
    statuses = requirements.requirement_status(items, [run.to_dict() for run in runs])
    return {
        "deadline": deadline.isoformat(),
        "seconds_left": requirements.time_left(deadline).total_seconds(),
        "items": [status.to_dict() for status in statuses],
    }


def requirements_note(
    item_id: str, text: str, *, path: Path = REQUIREMENTS_FILE
) -> dict[str, Any]:
    return requirements.set_note(item_id, text, path=path).to_dict()


def requirements_evidence_add(
    item_id: str,
    case_id: str,
    *,
    path: Path = REQUIREMENTS_FILE,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> dict[str, Any]:
    catalog.get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    return requirements.add_evidence(item_id, case_id, path=path).to_dict()


def requirements_evidence_remove(
    item_id: str, case_id: str, *, path: Path = REQUIREMENTS_FILE
) -> dict[str, Any]:
    return requirements.remove_evidence(item_id, case_id, path=path).to_dict()
