"""Command line front end of the project workbench.

Every subcommand calls one handler in `app.commands` and prints its result. Parsing,
dispatch and human formatting are kept apart; no domain logic lives here.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic_ai.models.test import TestModel

from app import commands
from app.paths import GUI_HOME, PROJECT_DIR

Handler = Callable[[argparse.Namespace], Any]
Renderer = Callable[[Any], None]
ArgsRenderer = Callable[[argparse.Namespace, Any], None]
ExitCode = Callable[[Any], int]

HANDLED_ERRORS = (LookupError, ValueError, FileExistsError, RuntimeError, SystemExit)
DEFAULT_COMPONENT = "order-gateway"
OUTCOME_LABELS = {
    "passed": "passed",
    "failed": "failed",
    "not_evaluated": "not evaluated",
    "errored": "ended with an error",
}


# Parsing -----------------------------------------------------------------------------


def _common_parser() -> argparse.ArgumentParser:
    """Flags accepted before or after any subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the result as JSON",
    )
    return common


def _ignoring_args(renderer: Renderer) -> ArgsRenderer:
    def render(_args: argparse.Namespace, result: Any) -> None:
        renderer(result)

    return render


def _command(
    subparsers: Any,
    name: str,
    help_text: str,
    handler: Handler,
    renderer: Renderer,
    common: argparse.ArgumentParser,
    exit_code: ExitCode | None = None,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        name, help=help_text, description=help_text, parents=[common]
    )
    parser.set_defaults(
        handler=handler, renderer=_ignoring_args(renderer), exit_code=exit_code
    )
    return parser


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--model", help="model name (default: the runtime default)")
    group.add_argument(
        "--offline", action="store_true", help="use an offline test model, no API calls"
    )
    parser.add_argument(
        "--approver", help='"approve_all", "deny_all" or "roles:a,b" (overrides case)'
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="model request limit per run (default: the harness's own, else 20)",
    )


def _add_cases(subparsers: Any, common: argparse.ArgumentParser) -> None:
    cases = subparsers.add_parser(
        "cases", help="list, show, validate and write cases", parents=[common]
    )
    sub = cases.add_subparsers(dest="cases_command", required=True)

    _command(sub, "list", "list cases", _cases_list, _render_cases_list, common)

    show = _command(
        sub,
        "show",
        "show a case's scenario and check",
        _cases_show,
        _render_cases_show,
        common,
    )
    show.add_argument("case_id")

    validate = _command(
        sub,
        "validate",
        "validate a scenario file and optional check file",
        _cases_validate,
        _render_validation,
        common,
        exit_code=_validation_exit_code,
    )
    validate.add_argument("scenario_file", type=Path)
    validate.add_argument("--check", type=Path, help="check file for the scenario")

    write = _command(
        sub,
        "write",
        "validate and write a case into the project",
        _cases_write,
        _render_written,
        common,
    )
    write.add_argument("scenario_file", type=Path)
    write.add_argument("--check", type=Path, help="check file for the scenario")
    write.add_argument("--force", action="store_true", help="overwrite existing files")

    draft = _command(
        sub,
        "draft",
        "draft a training case from one saved failing training run; writes nothing",
        _cases_draft,
        _render_draft,
        common,
    )
    draft.add_argument("set_id")
    draft.add_argument("run_id", help="run id (a unique prefix is enough)")
    draft.add_argument(
        "--span", help="span id to build the case around (default: the critic's blame)"
    )
    draft.add_argument(
        "--model", default="offline", help='author model (default: "offline")'
    )
    _add_live_options(draft)

    _command(
        sub,
        "schema",
        "show the keys a case editor offers",
        _cases_schema,
        _render_yaml,
        common,
    )


def _add_explore(subparsers: Any, common: argparse.ArgumentParser) -> None:
    explore = _command(
        subparsers,
        "explore",
        "step a case through the simulator without an agent",
        _explore,
        _render_nothing,
        common,
    )
    explore.add_argument("case_id")
    explore.add_argument("--ticks", type=int, default=30, help="ticks to advance")
    explore.add_argument(
        "--component", default=DEFAULT_COMPONENT, help="component whose metrics to show"
    )
    explore.add_argument("--logs", action="store_true", help="print each frame's logs")
    explore.set_defaults(renderer=_render_exploration)


def _add_runs(subparsers: Any, common: argparse.ArgumentParser) -> None:
    harnesses = subparsers.add_parser(
        "harnesses", help="list harnesses", parents=[common]
    )
    sub = harnesses.add_subparsers(dest="harnesses_command", required=True)
    _command(sub, "list", "list harnesses", _harnesses_list, _render_harnesses, common)

    run = _command(
        subparsers, "run", "run one harness on one case", _run, _render_run, common
    )
    run.add_argument("harness")
    run.add_argument("case_id")
    _add_model_options(run)
    run.add_argument("--save", metavar="LABEL", help="save the run as a result set")
    run.add_argument(
        "--memory",
        type=Path,
        metavar="PATH",
        help="persistent memory store: the team reads its lessons and learns from the run",
    )

    compare = _command(
        subparsers,
        "compare",
        "run harnesses on cases and summarise",
        _compare,
        _render_compare,
        common,
    )
    compare.add_argument(
        "--harness", action="append", required=True, help="harness name (repeatable)"
    )
    compare.add_argument(
        "--case", action="append", help="case id (repeatable; default all)"
    )
    compare.add_argument(
        "--reps", type=int, default=1, help="runs per harness and case"
    )
    _add_model_options(compare)
    compare.add_argument("--workers", type=int, default=4, help="parallel runs")
    compare.add_argument("--baseline", metavar="SET", help="result set to diff against")
    compare.add_argument(
        "--by", choices=("harness_case", "case"), default="harness_case"
    )
    compare.add_argument(
        "--save", metavar="LABEL", help="save the runs as a result set"
    )
    compare.add_argument(
        "--memory-snapshot",
        type=Path,
        metavar="PATH",
        help="memory file every run copies and reads frozen (default: an empty store per run)",
    )


def _add_results(subparsers: Any, common: argparse.ArgumentParser) -> None:
    results = subparsers.add_parser(
        "results", help="list, show and diff saved result sets", parents=[common]
    )
    sub = results.add_subparsers(dest="results_command", required=True)
    _command(
        sub,
        "list",
        "list saved result sets",
        _results_list,
        _render_results_list,
        common,
    )
    show = _command(
        sub, "show", "show one result set", _results_show, _render_results_show, common
    )
    show.add_argument("set_id")
    diff = _command(
        sub, "diff", "diff two result sets", _results_diff, _render_diff, common
    )
    diff.add_argument("baseline")
    diff.add_argument("current")
    diff.add_argument("--by", choices=("harness_case", "case"), default="harness_case")
    review = _command(
        sub,
        "review",
        "project one saved run per agent, check each role and blame one agent",
        _results_review,
        _render_review,
        common,
    )
    review.add_argument("set_id")
    review.add_argument("run_id", help="run id (a unique prefix is enough)")
    review.add_argument("--critic-model", default="offline", help="default: offline")
    _add_live_options(review)


def _add_live_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cap-usd",
        default="5.00",
        help="dollars of model spend allowed (default 5.00)",
    )
    parser.add_argument(
        "--approve-live",
        action="store_true",
        help="approve spending on live models (offline needs no approval)",
    )


def _add_improve(subparsers: Any, common: argparse.ArgumentParser) -> None:
    improve = subparsers.add_parser(
        "improve",
        help="improve one agent of the team, one version at a time",
        parents=[common],
    )
    sub = improve.add_subparsers(dest="improve_command", required=True)
    run = _command(
        sub,
        "run",
        "one candidate attempt for one agent: baseline, critic, proposer, decision",
        _improve_run,
        _render_improve_run,
        common,
    )
    run.add_argument(
        "--role",
        required=True,
        choices=("orchestrator", "network", "database", "remediation", "reviewer"),
        help="agent to improve (the reviewer is refused)",
    )
    run.add_argument(
        "--model", help='team model ("offline" for the stub; default: runtime default)'
    )
    run.add_argument("--reps", type=int, default=3, help="runs per case and arm")
    run.add_argument(
        "--critic-model",
        help="default: offline for an offline team, else the Sonnet model",
    )
    run.add_argument("--proposer-model", help="default: as the critic")
    run.add_argument("--workers", type=int, default=4, help="parallel runs")
    run.add_argument(
        "--memory-snapshot",
        type=Path,
        metavar="PATH",
        help="memory file each run copies frozen, minus lessons of test-split cases",
    )
    _add_live_options(run)
    test = _command(
        sub,
        "test",
        "run the held-out test split for one team; no critic or proposer",
        _improve_test,
        _render_improve_test,
        common,
    )
    test.add_argument(
        "--version", required=True, help="a team fingerprint or the path of a team.yaml"
    )
    test.add_argument("--model", help='team model ("offline" for the stub)')
    test.add_argument("--reps", type=int, default=3, help="runs per case")
    test.add_argument("--workers", type=int, default=4, help="parallel runs")
    _add_live_options(test)


def _add_requirements(subparsers: Any, common: argparse.ArgumentParser) -> None:
    requirements = subparsers.add_parser(
        "requirements", help="requirement status, notes and evidence", parents=[common]
    )
    sub = requirements.add_subparsers(dest="requirements_command", required=True)

    status = _command(
        sub,
        "status",
        "show requirement status",
        _requirements_status,
        _render_requirements,
        common,
    )
    status.add_argument(
        "--set", dest="set_id", help="result set (default: newest runs)"
    )

    note = _command(
        sub,
        "note",
        "set a requirement's note",
        _requirements_note,
        _render_requirement_item,
        common,
    )
    note.add_argument("item_id")
    note.add_argument("text")

    evidence = sub.add_parser(
        "evidence", help="add or remove evidence cases", parents=[common]
    )
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    add = _command(
        evidence_sub,
        "add",
        "add an evidence case",
        _evidence_add,
        _render_requirement_item,
        common,
    )
    add.add_argument("item_id")
    add.add_argument("case_id")
    remove = _command(
        evidence_sub,
        "remove",
        "remove an evidence case",
        _evidence_remove,
        _render_requirement_item,
        common,
    )
    remove.add_argument("item_id")
    remove.add_argument("case_id")


def _add_gui(subparsers: Any, common: argparse.ArgumentParser) -> None:
    gui = _command(
        subparsers,
        "gui",
        "launch the Streamlit GUI",
        _gui,
        _render_nothing,
        common,
        exit_code=_gui_exit_code,
    )
    gui.add_argument("--port", type=int, help="server port")


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog="mrx-project", description="Meridian project workbench", parents=[common]
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_cases(subparsers, common)
    _add_explore(subparsers, common)
    _add_runs(subparsers, common)
    _add_results(subparsers, common)
    _add_improve(subparsers, common)
    _add_requirements(subparsers, common)
    _add_gui(subparsers, common)
    return parser


# Handlers: one call into the command layer each --------------------------------------


def _model_from(args: argparse.Namespace) -> Any:
    return TestModel() if args.offline else args.model


def _read_text(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as failure:
        raise ValueError(f"cannot read {path}: {failure.strerror}") from failure


def _scenario_and_check(args: argparse.Namespace) -> tuple[str, str | None]:
    scenario = _read_text(args.scenario_file)
    assert scenario is not None
    return scenario, _read_text(args.check)


def _cases_list(_args: argparse.Namespace) -> Any:
    return commands.cases_list()


def _cases_show(args: argparse.Namespace) -> Any:
    return commands.cases_show(args.case_id)


def _cases_validate(args: argparse.Namespace) -> Any:
    scenario, check = _scenario_and_check(args)
    return commands.cases_validate(scenario, check)


def _cases_write(args: argparse.Namespace) -> Any:
    scenario, check = _scenario_and_check(args)
    return commands.cases_write(scenario, check, force=args.force)


def _cases_draft(args: argparse.Namespace) -> Any:
    return commands.cases_draft(
        args.set_id,
        args.run_id,
        span_id=args.span,
        model=args.model,
        cap_usd=args.cap_usd,
        approve_live=args.approve_live,
    )


def _cases_schema(_args: argparse.Namespace) -> Any:
    return commands.authoring_schema()


def _explore(args: argparse.Namespace) -> Any:
    return commands.explore(args.case_id, args.ticks)


def _harnesses_list(_args: argparse.Namespace) -> Any:
    return commands.harnesses_list()


def _run(args: argparse.Namespace) -> Any:
    return commands.run(
        args.harness,
        args.case_id,
        model=_model_from(args),
        approver=args.approver,
        max_requests=args.max_requests,
        save_label=args.save,
        memory=args.memory,
    )


def _print_progress(done: int, total: int, record: dict[str, Any]) -> None:
    print(
        f"{done}/{total} {record['harness']} {record['case_id']} {record['outcome']}",
        file=sys.stderr,
    )


def _compare(args: argparse.Namespace) -> Any:
    return commands.compare(
        args.harness,
        args.case or None,
        reps=args.reps,
        model=_model_from(args),
        approver=args.approver,
        max_requests=args.max_requests,
        max_workers=args.workers,
        baseline=args.baseline,
        by=args.by,
        save_label=args.save,
        memory_snapshot=args.memory_snapshot,
        on_progress=_print_progress,
    )


def _results_list(_args: argparse.Namespace) -> Any:
    return commands.results_list()


def _results_show(args: argparse.Namespace) -> Any:
    return commands.results_show(args.set_id)


def _results_diff(args: argparse.Namespace) -> Any:
    return commands.results_diff(args.baseline, args.current, by=args.by)


def _results_review(args: argparse.Namespace) -> Any:
    return commands.results_review(
        args.set_id,
        args.run_id,
        critic_model=args.critic_model,
        cap_usd=args.cap_usd,
        approve_live=args.approve_live,
    )


def _improve_run(args: argparse.Namespace) -> Any:
    return commands.improve_run(
        args.role,
        model=args.model,
        reps=args.reps,
        cap_usd=args.cap_usd,
        critic_model=args.critic_model,
        proposer_model=args.proposer_model,
        max_workers=args.workers,
        approve_live=args.approve_live,
        memory_snapshot=args.memory_snapshot,
    )


def _improve_test(args: argparse.Namespace) -> Any:
    return commands.improve_test(
        args.version,
        model=args.model,
        reps=args.reps,
        cap_usd=args.cap_usd,
        max_workers=args.workers,
        approve_live=args.approve_live,
    )


def _requirements_status(args: argparse.Namespace) -> Any:
    return commands.requirements_status(set_id=args.set_id)


def _requirements_note(args: argparse.Namespace) -> Any:
    return commands.requirements_note(args.item_id, args.text)


def _evidence_add(args: argparse.Namespace) -> Any:
    return commands.requirements_evidence_add(args.item_id, args.case_id)


def _evidence_remove(args: argparse.Namespace) -> Any:
    return commands.requirements_evidence_remove(args.item_id, args.case_id)


def _gui(args: argparse.Namespace) -> Any:
    command = [sys.executable, "-m", "streamlit", "run", str(GUI_HOME)]
    if args.port is not None:
        command += ["--server.port", str(args.port)]
    existing = os.environ.get("PYTHONPATH")
    pythonpath = (
        f"{PROJECT_DIR}{os.pathsep}{existing}" if existing else str(PROJECT_DIR)
    )
    done = subprocess.run(
        command, check=False, env={**os.environ, "PYTHONPATH": pythonpath}
    )
    return {"exit_code": done.returncode}


def _gui_exit_code(result: Any) -> int:
    return int(result["exit_code"])


def _validation_exit_code(result: Any) -> int:
    return 0 if result["valid"] else 1


# Human formatting --------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max(len(cell) for cell in column)
        for column in zip(headers, *rows, strict=False)
    ]
    lines = [
        "  ".join(
            cell.ljust(width) for cell, width in zip(row, widths, strict=True)
        ).rstrip()
        for row in [headers, *rows]
    ]
    return "\n".join(lines)


def _percent(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def _render_nothing(_result: Any) -> None:
    return None


def _render_yaml(result: Any) -> None:
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())


def _render_cases_list(result: list[dict[str, Any]]) -> None:
    rows = [
        [
            case["case_id"],
            case["session"],
            "yes" if case["check_path"] else "no",
            case["title"],
        ]
        for case in result
    ]
    print(_table(["case", "session", "check", "title"], rows))


def _render_cases_show(result: dict[str, Any]) -> None:
    print(result["scenario"].rstrip())
    print("---")
    print(result["check"].rstrip() if result["check"] else "(no check)")


def _render_validation(result: dict[str, Any]) -> None:
    if result["valid"]:
        print(f"valid: {result['case_id']}")
        return
    for message in result["scenario_errors"]:
        print(f"scenario: {message}")
    for message in result["check_errors"]:
        print(f"check: {message}")


def _render_written(result: dict[str, Any]) -> None:
    _render_yaml(result)


def _frame_line(frame: dict[str, Any], component: str) -> str:
    metrics = frame["components"].get(component)
    shown = (
        f"latency_ms={metrics['latency_ms']} error_rate={metrics['error_rate']} "
        f"queue_depth={metrics['queue_depth']}"
        if metrics
        else f"({component}: no such component)"
    )
    return (
        f"tick {frame['tick']:>3}  {frame['time']}  {component} {shown}  "
        f"alerts={len(frame['alerts_open'])} logs={len(frame['logs'])} "
        f"faults={len(frame['active_faults'])}"
    )


def _render_exploration(args: argparse.Namespace, result: dict[str, Any]) -> None:
    _render_exploration_frames(result, args.component, args.logs)


def _render_exploration_frames(
    result: dict[str, Any], component: str, show_logs: bool
) -> None:
    print(f"{result['case_id']}: {result['title']}")
    _render_yaml(result["brief"])
    for frame in result["frames"]:
        print(_frame_line(frame, component))
        if not show_logs:
            continue
        for line in frame["logs"]:
            print(f"    {json.dumps(line, ensure_ascii=False)}")


def _render_harnesses(result: list[dict[str, Any]]) -> None:
    rows = [
        [h["name"], h["source"], "read-only" if h["read_only"] else "editable"]
        for h in result
    ]
    print(_table(["harness", "source", "access"], rows))


def _render_run(result: dict[str, Any]) -> None:
    record = result["record"]
    outcome = OUTCOME_LABELS[record["outcome"]]
    print(f"{record['harness']} on {record['case_id']}: {outcome}")
    for check in record["checks"]:
        mark = "✓" if check["passed"] else "✗"
        print(f"  {mark} {check['name']}: {check['detail']}")
    print(
        f"tokens={record['input_tokens']} requests={record['requests']} "
        f"end_tick={record['end_tick']}"
    )
    _render_lessons(record)
    if record["error"]:
        print(f"error: {record['error']}")
    if result["result_set"]:
        print(f"saved: {result['result_set']}")


def _render_lessons(record: dict[str, Any]) -> None:
    lessons = record["lessons"]
    if record["memory_fingerprint"]:
        print(f"memory at start: {record['memory_fingerprint'][:12]}")
    for use in lessons.get("cited", []):
        refs = ", ".join(use["evidence_refs"]) or "no evidence refs"
        blamed = " IMPLICATED" if use["implicated"] else ""
        print(f"lesson cited by {use['role']}: {use['lesson_id']} ({refs}){blamed}")
    for update in lessons.get("updates", []):
        print(f"lesson {update['action']}: {update['result_id']}")


def _render_draft(result: dict[str, Any]) -> None:
    print(f"draft {result['case_id']} ({result['kind']})")
    print(
        f"source: set {result['source_set_id']}, run {result['source_run_id']} "
        f"({result['source_case_id']}), span {result['blamed_span_id']}"
    )
    print("\n# scenario\n" + result["scenario_yaml"].rstrip())
    print("\n# check\n" + result["check_yaml"].rstrip())
    print("\nrehearsal:")
    for item in result["rehearsal"]:
        wanted = "pass" if item["expected_pass"] else "fail"
        got = "passed" if item["passed"] else "failed"
        print(f"  {item['trajectory']}: expected {wanted}, {got}")
        for check in item["checks"]:
            mark = "✓" if check["passed"] else "✗"
            print(f"    {mark} {check['name']}: {check['detail']}")
    name = result["case_id"]
    print(
        "\nNothing was written. After review, save the two YAMLs above and admit them with:\n"
        f"  bin/mrx-project cases write {name}.yaml --check {name}.check.yaml"
    )


def _summary_table(summary: list[dict[str, Any]]) -> str:
    rows = [
        [
            row["case_id"],
            row["harness"],
            f"{_percent(row['pass_rate'])} ({row['passed']}/{row['runs']})",
            str(row["errors"]),
            f"{row['mean_input_tokens']:.0f}",
            ", ".join(
                f"{name}x{count}" for name, count in row["failing_checks"].items()
            )
            or "-",
        ]
        for row in summary
    ]
    return _table(
        ["case", "harness", "pass rate", "errors", "mean tokens", "failing checks"],
        rows,
    )


def _diff_table(diff: list[dict[str, Any]]) -> str:
    rows = [
        [
            row["case_id"],
            row.get("harness", "-"),
            _percent(row["baseline_rate"]),
            _percent(row["current_rate"]),
            row["status"],
        ]
        for row in diff
    ]
    return _table(["case", "harness", "baseline", "current", "status"], rows)


def _render_compare(result: dict[str, Any]) -> None:
    print(_summary_table(result["summary"]))
    if result["diff"] is not None:
        print()
        print(_diff_table(result["diff"]))
    if result["result_set"]:
        print(f"\nsaved: {result['result_set']}")


def _render_results_list(result: list[dict[str, Any]]) -> None:
    rows = [
        [
            row["set_id"],
            row["label"],
            _percent(row["pass_rate"]),
            str(row["runs"]),
            ",".join(row["models"]),
        ]
        for row in result
    ]
    print(_table(["set", "label", "pass rate", "runs", "models"], rows))


def _render_results_show(result: dict[str, Any]) -> None:
    dirty = " (dirty)" if result["dirty"] else ""
    print(
        f"{result['set_id']}  label={result['label']}  created={result['created_at']}"
    )
    print(f"commit={result['commit']}{dirty}  models={','.join(result['models'])}")
    print()
    print(_summary_table(result["summary"]))


def _render_review(result: dict[str, Any]) -> None:
    print(result["view"])
    print("\nrole checks:")
    for check in result["role_checks"]:
        print(
            f"  {check['role']} {check['check']}: {check['passed']} ({check['detail']})"
        )
    blame = result["blame"]
    if blame is None:
        print(f"\nno usable blame: {result['blame_error']}")
        return
    print(f"\nblame: {blame['role']} at span {blame['span_id']}")
    print(f"  problem: {blame['problem']}")
    print(f"  fix: {blame['fix_hint']}")


def _render_improve_run(result: dict[str, Any]) -> None:
    attempt = result["attempt"]
    print(
        f"{attempt['role']}: attempt {attempt['invocation_id']} {attempt['status']}, "
        f"parent {attempt['parent_version']}, candidate {attempt['candidate_version'] or '-'}"
    )
    if attempt["change"]:
        edit = attempt["change"]["edit"]
        print(f"change: {edit['field']} = {edit['value']!r}")
        print(f"why: {attempt['change']['rationale']}")
    if attempt["detail"]:
        print(f"detail: {attempt['detail']}")
    decision = attempt["decision"]
    if decision:
        print(f"decision: {'ADOPT' if decision['adopt'] else 'REJECT'}")
        print(
            f"  training {_percent(decision['train_baseline_rate'])} to "
            f"{_percent(decision['train_candidate_rate'])}"
        )
        for reason in decision["reasons"]:
            print(f"  - {reason}")
    print("result sets: " + ", ".join(f"{k}={v}" for k, v in attempt["sets"].items()))
    print(
        f"teams: baseline {attempt['baseline_team']}, candidate {attempt['candidate_team'] or '-'}; "
        f"splits {attempt['splits_fingerprint'][:12]}; spent ${attempt['spent_usd']}"
    )
    print(f"lineage: {result['lineage_file']}")
    if attempt["adopted_file"]:
        print(f"kept: {attempt['adopted_file']}")
        print(result["pin"])


def _render_improve_test(result: dict[str, Any]) -> None:
    print(
        f"team {result['team']}: test {result['passed']}/{result['runs']} "
        f"({_percent(result['pass_rate'])}); result set {result['result_set']}"
    )


def _render_diff(result: list[dict[str, Any]]) -> None:
    print(_diff_table(result))


def _time_left_label(seconds: float) -> str:
    if seconds < 0:
        return "deadline passed"
    days, remainder = divmod(int(seconds), 86400)
    return f"{days} days {remainder // 3600} hours left"


def _render_requirements(result: dict[str, Any]) -> None:
    print(f"deadline {result['deadline']}: {_time_left_label(result['seconds_left'])}")
    group = None
    for item in result["items"]:
        requirement = item["requirement"]
        if requirement["group"] != group:
            group = requirement["group"]
            print(f"\n{group}")
        evidence = ", ".join(requirement["evidence"]) or "-"
        print(
            f"  {item['status']:<12} {requirement['id']}  {requirement['title']}  [{evidence}]"
        )


def _render_requirement_item(result: dict[str, Any]) -> None:
    evidence = ", ".join(result["evidence"]) or "-"
    print(f"{result['id']}: evidence=[{evidence}] notes={result['notes']!r}")


# Entry point -------------------------------------------------------------------------


def _print_result(args: argparse.Namespace, result: Any) -> None:
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    args.renderer(args, result)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except HANDLED_ERRORS as failure:
        print(f"error: {failure}", file=sys.stderr)
        return 1
    _print_result(args, result)
    return args.exit_code(result) if args.exit_code else 0


if __name__ == "__main__":
    sys.exit(main())
