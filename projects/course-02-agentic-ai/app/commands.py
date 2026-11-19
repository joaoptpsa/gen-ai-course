"""The workbench's command layer: one handler per CLI subcommand.

The CLI parses arguments and prints what a handler returns; the GUI calls the same
handlers in-process. Every handler returns JSON-serialisable data and raises
LookupError, ValueError or FileExistsError with a readable message on bad input.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import yaml
from agent.lessons import memory_fingerprint, snapshot_memory

from app.core import (
    authoring,
    case_splits,
    catalog,
    explorer,
    requirements,
    results,
    runner,
)
from app.core.model_budget import DEFAULT_CAP_USD, ModelBudget
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


def cases_draft(
    set_id: str,
    run_id: str,
    *,
    span_id: str | None = None,
    model: str = "offline",
    cap_usd: Any = DEFAULT_CAP_USD,
    approve_live: bool = False,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, Any]:
    """Draft a training case from one saved failing training run. Nothing is written.

    The blamed span is `span_id`, or the critic's validated blame (same model as the author).
    The pair goes to a human; `cases write` admits it after review.
    """
    from agent import case_drafts, loop, pieces
    from agent.suite import trusted_facts

    from app.core import team_trace

    _approve_live({"author": model}, 1 if span_id else 2, cap_usd, approve_live)
    record = results.find_run(
        results.load_result_set(set_id, results_dir=results_dir), run_id
    )
    splits = case_splits.load_splits(
        catalog.list_cases(cases_dir=cases_dir, checks_dir=checks_dir)
    )
    split = splits.split_of(record.case_id)
    if split != "train":
        raise ValueError(
            f"run {record.run_id} is a {record.case_id} run, which is not in the train "
            f"split ({split or 'unassigned'}); only training failures may seed a case"
        )
    if not record.spans_file:
        raise LookupError(f"run {record.run_id} has no saved spans")
    trace = team_trace.project_trace(
        team_trace.load_spans(results_dir / record.spans_file)
    )
    facts = trusted_facts(record, checks_dir=checks_dir)
    verdicts = team_trace.check_roles(trace, facts)
    budget = ModelBudget(cap_usd)
    blamed = span_id
    if blamed is None:
        critic = pieces.agent_model(model, pieces.offline_critic(), budget)
        review = loop.review_run(record, critic_model=critic, results_dir=results_dir)
        if review["blame"] is None:
            raise ValueError(
                f"the critic gave no usable blame: {review['blame_error']}"
            )
        blamed = review["blame"]["span_id"]
    if blamed not in trace.spans:
        raise LookupError(f"span {blamed!r} is not in the spans of run {record.run_id}")
    failure = case_drafts.summarize_failure(
        trace, set_id, blamed, verdicts, split="train"
    )
    author = pieces.agent_model(model, case_drafts.offline_author(), budget)
    draft = case_drafts.draft_case(
        failure, author, cases_dir=cases_dir, checks_dir=checks_dir
    )
    return {
        **draft.model_dump(mode="json"),
        "source_case_id": record.case_id,
        "blamed_span_id": blamed,
    }


def cases_round_trip_loss(
    original_scenario: str,
    original_check: str | None,
    rebuilt_scenario: str,
    rebuilt_check: str,
) -> dict[str, Any]:
    """What rewriting a case from a form would lose: dropped keys and comments, per file.

    GUI-only: the CLI writes files as given, so it has no form to lose anything.
    """
    check = (
        authoring.round_trip_loss(original_check, rebuilt_check)
        if original_check
        else {"dropped": [], "comments": False}
    )
    return {
        "scenario": authoring.round_trip_loss(original_scenario, rebuilt_scenario),
        "check": check,
    }


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
    max_requests: int | None = None,
    save_label: str | None = None,
    memory: Path | None = None,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
    harnesses_dir: Path = HARNESSES_DIR,
    sessions_dir: Path = SESSIONS_DIR,
    results_dir: Path = RESULTS_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Run one harness on one case. `approver` overrides the scenario's approver ("approve_all", "deny_all", "roles:a,b").

    `memory` is a persistent store the team keeps lessons in: it is read during the run and
    settled after the evaluation.
    """
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
        memory_path=memory,
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
    max_requests: int | None = None,
    max_workers: int = 4,
    baseline: str | None = None,
    by: Literal["harness_case", "case"] = "harness_case",
    save_label: str | None = None,
    memory_snapshot: Path | None = None,
    on_progress: Progress | None = None,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
    harnesses_dir: Path = HARNESSES_DIR,
    sessions_dir: Path = SESSIONS_DIR,
    results_dir: Path = RESULTS_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Run every harness on every case `reps` times; all cases when `case_ids` is None.

    With `memory_snapshot`, every run gets its own frozen copy of that memory file, and the source
    must be unchanged when the matrix ends.
    """
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

    with _source_unchanged(memory_snapshot) as source_fingerprint:
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
            memory_snapshot=memory_snapshot,
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
        "memory_fingerprint": source_fingerprint,
        "runs": [record.to_dict() for record in records],
    }


@contextmanager
def _source_unchanged(path: Path | None) -> Iterator[str]:
    """Yield the memory file's fingerprint; fail when it differs after the block."""
    if path is None:
        yield ""
        return
    if not Path(path).is_file():
        raise LookupError(f"memory snapshot {path} does not exist")
    before = memory_fingerprint(path)
    yield before
    after = memory_fingerprint(path)
    if after != before:
        raise RuntimeError(
            f"memory snapshot {path} changed during the run: {before[:12]} -> {after[:12]}"
        )


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


# Version loop ------------------------------------------------------------------------

OFFLINE_MODEL = "offline"
LIVE_AGENT_MODEL = "anthropic:claude-sonnet-5-5"


def _approve_live(
    names: dict[str, str], runs: int, cap_usd: Any, approved: bool
) -> None:
    live = {role: name for role, name in names.items() if name != OFFLINE_MODEL}
    if not live or approved:
        return
    models = ", ".join(f"{role}={name}" for role, name in live.items())
    raise ValueError(
        f"live models need approval: {models}; about {runs} team runs, "
        f"capped at ${cap_usd} of model spend; rerun with --approve-live to go ahead"
    )


def improve_run(
    role: str,
    *,
    model: str | None = None,
    reps: int = 3,
    cap_usd: Any = DEFAULT_CAP_USD,
    critic_model: str | None = None,
    proposer_model: str | None = None,
    max_workers: int = 4,
    approve_live: bool = False,
    memory_snapshot: Path | None = None,
    harnesses_dir: Path = HARNESSES_DIR,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, Any]:
    """One candidate attempt for one agent of the team (see agent/loop.py).

    Every run starts from a fresh empty store, or from its own frozen copy of `memory_snapshot`
    with the lessons of test-split cases removed.
    """
    from agent import loop, pieces, suite

    if reps < 1:
        raise ValueError(f"reps must be >= 1, got {reps}")
    team_name = model or default_model()
    agent_default = OFFLINE_MODEL if team_name == OFFLINE_MODEL else LIVE_AGENT_MODEL
    names = {
        "team": team_name,
        "critic": critic_model or agent_default,
        "proposer": proposer_model or agent_default,
    }
    splits = case_splits.load_splits(catalog.list_cases())
    runs = (len(splits.train) + len(splits.valid)) * reps * 2
    _approve_live(names, runs, cap_usd, approve_live)
    budget = ModelBudget(cap_usd)
    config = loop.LoopConfig(
        role=role,  # type: ignore[arg-type]
        reps=reps,
        splits=splits,
        critic_model=pieces.agent_model(
            names["critic"], pieces.offline_critic(), budget
        ),
        proposer_model=pieces.agent_model(
            names["proposer"], pieces.offline_proposer(), budget
        ),
        model_names=names,
        harnesses_dir=harnesses_dir,
        results_dir=results_dir,
        lineage_file=harnesses_dir / "versions" / "lineage.jsonl",
    )
    team = pieces.team_model(team_name, budget)
    with _eligible_snapshot(memory_snapshot, splits.test) as (eligible, fingerprint):
        compare = (
            suite.workbench_compare(
                team, results_dir=results_dir, max_workers=max_workers
            )
            if eligible is None
            else loop.snapshot_compare(
                team,
                memory_snapshot=eligible,
                results_dir=results_dir,
                max_workers=max_workers,
            )
        )
        attempt = loop.run_iteration(config, compare, budget)
    return {
        "attempt": attempt.model_dump(mode="json"),
        "lineage_file": str(config.lineage_file),
        "pin": loop.pin_instruction(attempt, harnesses_dir),
        "memory_fingerprint": fingerprint,
    }


@contextmanager
def _eligible_snapshot(
    source: Path | None, test_cases: list[str]
) -> Iterator[tuple[Path | None, str]]:
    """A copy of the memory without the lessons of test-split cases, and its fingerprint.

    The source must be unchanged afterwards. Lessons carry their origin case in `source_ref`
    (`<run>@<case>`), so the filter needs no saved results.
    """
    if source is None:
        yield None, ""
        return
    with (
        _source_unchanged(source),
        tempfile.TemporaryDirectory(prefix="workbench-eligible-") as directory,
    ):
        eligible = Path(directory) / "memory.db"
        fingerprint = snapshot_memory(
            source, eligible, frozen=True, exclude_cases=test_cases
        )
        yield eligible, fingerprint


def improve_test(
    version: str,
    *,
    model: str | None = None,
    reps: int = 3,
    cap_usd: Any = DEFAULT_CAP_USD,
    max_workers: int = 4,
    approve_live: bool = False,
    harnesses_dir: Path = HARNESSES_DIR,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, Any]:
    """Run the held-out test split for one team (a fingerprint or a team.yaml path)."""
    from agent import loop, pieces, suite

    team_name = model or default_model()
    splits = case_splits.load_splits(catalog.list_cases())
    _approve_live({"team": team_name}, len(splits.test) * reps, cap_usd, approve_live)
    budget = ModelBudget(cap_usd)
    compare = suite.workbench_compare(
        pieces.team_model(team_name, budget),
        results_dir=results_dir,
        max_workers=max_workers,
    )
    return loop.run_test(
        version,
        splits=splits,
        reps=reps,
        compare=compare,
        harnesses_dir=harnesses_dir,
        lineage_file=harnesses_dir / "versions" / "lineage.jsonl",
    )


def results_review(
    set_id: str,
    run_id: str,
    *,
    critic_model: str = OFFLINE_MODEL,
    cap_usd: Any = DEFAULT_CAP_USD,
    approve_live: bool = False,
    results_dir: Path = RESULTS_DIR,
) -> dict[str, Any]:
    """Project one saved run: spans per agent, role checks and the critic's validated blame."""
    from agent import loop, pieces

    _approve_live({"critic": critic_model}, 1, cap_usd, approve_live)
    result_set = results.load_result_set(set_id, results_dir=results_dir)
    record = results.find_run(result_set, run_id)
    model = pieces.agent_model(
        critic_model, pieces.offline_critic(), ModelBudget(cap_usd)
    )
    return loop.review_run(record, critic_model=model, results_dir=results_dir)


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
