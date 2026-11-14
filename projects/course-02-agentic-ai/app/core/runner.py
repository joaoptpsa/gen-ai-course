"""Run harnesses on cases and record what happened."""

from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        return cls(**data)


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
    commit, dirty = git_state(repo_root)
    harness = load_harness(harness_path)
    options = {
        "model": model,
        "max_requests": max_requests,
        "solutions_dir": checks_dir,
    }
    started_at = _now()
    started = datetime.now(timezone.utc)
    if approver is None:
        run = run_incident(harness, case_path, **options)
    else:
        run = _run_with_approver(harness, case_path, approver, **options)
    duration = (datetime.now(timezone.utc) - started).total_seconds()

    evaluation = run.evaluation
    return RunRecord(
        run_id=uuid.uuid4().hex[:8],
        harness=harness_name or Path(harness_path).stem,
        harness_path=str(harness_path),
        case_id=run.scenario_id,
        case_path=str(case_path),
        model=_model_name(model),
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
    )


def _error_record(
    harness_name: str,
    harness_path: Path,
    case_path: Path,
    model: Any,
    approver: dict[str, Any] | None,
    failure: Exception,
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
        except Exception as failure:  # noqa: BLE001 a failed run becomes a visible error record
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
