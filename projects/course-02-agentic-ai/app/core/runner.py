"""Run harnesses on cases and record what happened."""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from opentelemetry.trace import Span

from app.core import telemetry
from app.paths import CHECKS_DIR, REPO_ROOT
from meridian.agent_runtime import (
    default_model,
    load_harness,
    model_trace,
    require_api_key,
    run_incident,
)
from meridian.evaluate import report_as_dict

APPROVER_FORMS = '"approve_all", "deny_all" or "roles:<role>,<role>"'

Outcome = Literal["passed", "failed", "not_evaluated", "errored"]

# meridian registers every load of a harness file under one module name, and pydantic resolves a
# model's annotations through that name. Two threads loading at once leave one of them with a
# report model that is "not fully defined", so loads take turns.
_HARNESS_LOADING = threading.Lock()


def outcome_of(error: str | None, passed: bool | None) -> Outcome:
    """How a run ended, read from its error and its evaluation together.

    An error wins: the run did not start, or the agent stopped without a report. meridian still
    evaluates a run without a report, and `passed` keeps that verdict so pass rates match the
    course's own suite; `errored` says the verdict is not the whole story.
    """
    if error:
        return "errored"
    if passed is None:
        return "not_evaluated"
    if passed:
        return "passed"
    return "failed"


@dataclass
class RunRecord:
    run_id: str
    harness: str
    harness_path: str
    case_id: str
    case_path: str
    model: str
    approver: dict[str, Any]
    commit: str
    dirty: bool
    started_at: str
    duration_s: float
    error: str | None
    report: dict[str, Any]
    passed: bool | None
    checks: list[dict[str, Any]]
    input_tokens: int
    requests: int
    end_tick: int
    trace: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    messages: list[dict[str, str]]
    # Records saved before tracing have no trace, hence the defaults.
    trace_id: str = ""
    spans_file: str | None = None
    # Set for team harnesses: the content fingerprint of the resolved team and its topology.
    team_version: str = ""
    topology: str = ""
    # Masked span records; saved to their own file (spans_file), never inside the record.
    spans: list[dict[str, Any]] = field(default_factory=list)

    @property
    def outcome(self) -> Outcome:
        return outcome_of(self.error, self.passed)

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        del record["spans"]
        record["outcome"] = self.outcome
        return record

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        # The outcome is derived, so a stored one is dropped instead of trusted.
        fields = {key: value for key, value in data.items() if key != "outcome"}
        return cls(**fields)


def _git(repo_root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo_root}: {done.stderr.strip()}"
        )
    return done.stdout


def git_state(repo_root: Path = REPO_ROOT) -> tuple[str, bool]:
    commit = _git(repo_root, "rev-parse", "HEAD").strip()
    dirty = bool(_git(repo_root, "status", "--porcelain").strip())
    return commit, dirty


def parse_approver(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned in ("approve_all", "deny_all"):
        return {"mode": cleaned}
    if cleaned.startswith("roles:"):
        roles = [
            role.strip()
            for role in cleaned.removeprefix("roles:").split(",")
            if role.strip()
        ]
        if roles:
            return {"approve_roles": roles}
    raise ValueError(f"Unknown approver {text!r}; accepted forms: {APPROVER_FORMS}")


def _model_name(model: Any) -> str:
    if isinstance(model, str):
        return model
    return str(getattr(model, "model_name", None) or type(model).__name__)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_with_approver(
    harness: Any, case_path: Path, approver: dict[str, Any], **kwargs: Any
) -> Any:
    scenario = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    scenario["approver"] = approver
    with tempfile.TemporaryDirectory(prefix="workbench-case-") as directory:
        override_path = Path(directory) / case_path.name
        override_path.write_text(
            yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8"
        )
        return run_incident(harness, override_path, **kwargs)


def run_case(
    harness_path: Path,
    case_path: Path,
    *,
    harness_name: str | None = None,
    model: Any = None,
    approver: dict[str, Any] | None = None,
    max_requests: int = 20,
    checks_dir: Path = CHECKS_DIR,
    repo_root: Path = REPO_ROOT,
) -> RunRecord:
    if model is None:
        require_api_key()
        model = default_model()
    tracing = telemetry.configure_tracing()
    commit, dirty = git_state(repo_root)
    with _HARNESS_LOADING:
        harness = load_harness(harness_path)
    options = {
        "model": model,
        "max_requests": max_requests,
        "solutions_dir": checks_dir,
    }
    run_id = uuid.uuid4().hex[:8]
    name = harness_name or Path(harness_path).stem
    model_name = _model_name(model)
    root_attributes = {
        "meridian.run_id": run_id,
        "meridian.harness": name,
        # The file name until the scenario's own id is known; a run that raises keeps it.
        "meridian.case_id": case_path.stem,
        "meridian.case_path": str(case_path),
        "meridian.model": model_name,
        "meridian.approver": json.dumps(approver or {}),
        "meridian.commit": commit,
        "meridian.dirty": dirty,
    }
    describe_run = getattr(harness, "run_attributes", None)
    harness_attributes: dict[str, str] = describe_run() if describe_run else {}
    root_attributes.update(harness_attributes)
    started_at = _now()
    started = datetime.now(timezone.utc)
    with telemetry.run_span(tracing, root_attributes) as run_trace:
        if approver is None:
            run = run_incident(harness, case_path, **options)
        else:
            run = _run_with_approver(harness, case_path, approver, **options)
        _trace_simulator_facts(tracing, run_trace.root, run)
    duration = (datetime.now(timezone.utc) - started).total_seconds()

    evaluation = run.evaluation
    return RunRecord(
        run_id=run_id,
        harness=name,
        harness_path=str(harness_path),
        case_id=run.scenario_id,
        case_path=str(case_path),
        model=model_name,
        approver=approver or {},
        commit=commit,
        dirty=dirty,
        started_at=started_at,
        duration_s=round(duration, 3),
        error=run.error,
        report=_json_safe(report_as_dict(run.report)),
        passed=evaluation.passed if evaluation else None,
        checks=[
            {"name": c.name, "passed": c.passed, "detail": c.detail}
            for c in evaluation.checks
        ]
        if evaluation
        else [],
        input_tokens=int(run.extra.get("input_tokens", 0)),
        requests=int(run.extra.get("requests", 0)),
        end_tick=int(run.extra.get("end_tick", 0)),
        trace=[_json_safe(asdict(call)) for call in run.trace],
        approvals=_json_safe(run.sim.approvals),
        messages=[
            {"kind": kind, "text": text} for kind, text in model_trace(run.messages)
        ],
        trace_id=run_trace.trace_id,
        team_version=harness_attributes.get("meridian.team_version", ""),
        topology=harness_attributes.get("meridian.topology", ""),
        spans=run_trace.spans,
    )


def _event_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    return json.dumps(value, default=str)


def _trace_simulator_facts(tracing: telemetry.Tracing, root: Span, run: Any) -> None:
    """Add what PydanticAI cannot see: the simulator's tool log, approvals and check verdicts.

    Verdicts carry check names only. A check's detail can hold the expected answer (a change
    id, say), which a proposer reading the trace must not see.
    """
    root.set_attribute("meridian.case_id", run.scenario_id)
    root.set_attribute("meridian.end_tick", int(run.extra.get("end_tick", 0)))
    if run.error:
        root.set_attribute("meridian.error", run.error)
    for call in run.trace:
        attributes = {
            "meridian.step": call.step,
            "meridian.tick": call.tick,
            "meridian.time": call.time,
            "meridian.tool": call.tool,
        }
        if call.error:
            attributes["meridian.error"] = call.error
        root.add_event("meridian.tool_call", attributes)
    for approval in run.sim.approvals:
        attributes = {
            f"meridian.{key}": _event_value(value) for key, value in approval.items()
        }
        root.add_event("meridian.approval", attributes)
    evaluation = run.evaluation
    # The workbench's own verdict, so the dashboard agrees with saved results.
    root.set_attribute(
        "meridian.outcome",
        outcome_of(run.error, evaluation.passed if evaluation else None),
    )
    if evaluation is None:
        return
    passed = [check.name for check in evaluation.checks if check.passed]
    failed = [check.name for check in evaluation.checks if not check.passed]
    root.set_attribute("meridian.passed", bool(evaluation.passed))
    with tracing.tracer.start_as_current_span("meridian.evaluate") as span:
        span.set_attribute("meridian.passed", bool(evaluation.passed))
        span.set_attribute("meridian.checks_passed", passed)
        span.set_attribute("meridian.checks_failed", failed)


def _error_record(
    harness_name: str,
    harness_path: Path,
    case_path: Path,
    model: Any,
    approver: dict[str, Any] | None,
    failure: BaseException,
    repo_root: Path,
) -> RunRecord:
    commit, dirty = git_state(repo_root)
    return RunRecord(
        run_id=uuid.uuid4().hex[:8],
        harness=harness_name,
        harness_path=str(harness_path),
        case_id=case_path.stem,
        case_path=str(case_path),
        model=_model_name(model) if model is not None else "default",
        approver=approver or {},
        commit=commit,
        dirty=dirty,
        started_at=_now(),
        duration_s=0.0,
        error=f"{type(failure).__name__}: {failure}",
        report={},
        passed=False,
        checks=[],
        input_tokens=0,
        requests=0,
        end_tick=0,
        trace=[],
        approvals=[],
        messages=[],
    )


def run_matrix(
    runs: list[tuple[str, Path, Path]],
    *,
    reps: int = 1,
    model: Any = None,
    approver: dict[str, Any] | None = None,
    max_requests: int = 20,
    max_workers: int = 4,
    on_progress: Callable[[int, int, RunRecord], None] | None = None,
    checks_dir: Path = CHECKS_DIR,
    repo_root: Path = REPO_ROOT,
) -> list[RunRecord]:
    # Resolve the model once: a missing API key must stop the matrix before any worker starts.
    if model is None:
        require_api_key()
        model = default_model()
    # Tracing is set up once, before the workers, so they share one provider.
    telemetry.configure_tracing()
    jobs = [(name, harness, case) for name, harness, case in runs for _ in range(reps)]

    def run_job(job: tuple[str, Path, Path]) -> RunRecord:
        name, harness, case = job
        try:
            return run_case(
                harness,
                case,
                harness_name=name,
                model=model,
                approver=approver,
                max_requests=max_requests,
                checks_dir=checks_dir,
                repo_root=repo_root,
            )
        # meridian raises SystemExit for bad input (unknown role, harness without build_agent);
        # one such run must not discard the others, which may already have cost money.
        except (Exception, SystemExit) as failure:  # noqa: BLE001 a failed run becomes a visible error record
            return _error_record(
                name, harness, case, model, approver, failure, repo_root
            )

    records: list[RunRecord | None] = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_job, job): index for index, job in enumerate(jobs)}
        for done, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            records[futures[future]] = record
            if on_progress:
                on_progress(done, len(jobs), record)
    return [record for record in records if record is not None]
