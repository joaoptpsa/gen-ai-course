"""Save, load and compare sets of run records."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.core.runner import RunRecord, git_state
from app.paths import REPO_ROOT, RESULTS_DIR


@dataclass
class ResultSet:
    set_id: str
    label: str
    created_at: str
    commit: str
    dirty: bool
    models: list[str]
    runs: list[RunRecord]

    def to_dict(self) -> dict[str, Any]:
        data = {
            key: getattr(self, key)
            for key in ("set_id", "label", "created_at", "commit", "dirty", "models")
        }
        data["runs"] = [run.to_dict() for run in self.runs]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultSet:
        runs = [RunRecord.from_dict(run) for run in data["runs"]]
        return cls(
            data["set_id"],
            data["label"],
            data["created_at"],
            data["commit"],
            data["dirty"],
            data["models"],
            runs,
        )


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "run"


def _truncate_result(result: Any, max_chars: int) -> Any:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= max_chars:
        return result
    return {"truncated": True, "chars": len(text), "preview": text[:max_chars]}


def _truncated_copy(run: RunRecord, max_chars: int) -> RunRecord:
    data = run.to_dict()
    data["trace"] = [
        {**step, "result": _truncate_result(step["result"], max_chars)}
        for step in data["trace"]
    ]
    return RunRecord.from_dict(json.loads(json.dumps(data)))


def save_result_set(
    runs: list[RunRecord],
    label: str,
    *,
    results_dir: Path = RESULTS_DIR,
    repo_root: Path = REPO_ROOT,
    max_result_chars: int = 2000,
) -> ResultSet:
    now = datetime.now(timezone.utc)
    commit, dirty = git_state(repo_root)
    result_set = ResultSet(
        set_id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{_slug(label)}",
        label=label,
        created_at=now.isoformat(timespec="seconds"),
        commit=commit,
        dirty=dirty,
        models=sorted({run.model for run in runs}),
        runs=[_truncated_copy(run, max_result_chars) for run in runs],
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{result_set.set_id}.json"
    path.write_text(
        json.dumps(result_set.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result_set


def _pass_rate(runs: list[RunRecord]) -> float | None:
    evaluated = [run for run in runs if run.passed is not None]
    if not evaluated:
        return None
    return sum(1 for run in evaluated if run.passed) / len(evaluated)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as failure:
        raise ValueError(
            f"Result file {path} is not valid JSON: {failure}"
        ) from failure


def list_result_sets(*, results_dir: Path = RESULTS_DIR) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(results_dir.glob("*.json")):
        result_set = ResultSet.from_dict(_read_json(path))
        rows.append(
            {
                "set_id": result_set.set_id,
                "label": result_set.label,
                "created_at": result_set.created_at,
                "commit": result_set.commit,
                "dirty": result_set.dirty,
                "models": result_set.models,
                "runs": len(result_set.runs),
                "pass_rate": _pass_rate(result_set.runs),
            }
        )
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


def load_result_set(set_id: str, *, results_dir: Path = RESULTS_DIR) -> ResultSet:
    path = results_dir / f"{set_id}.json"
    if not path.is_file():
        known = (
            ", ".join(
                row["set_id"] for row in list_result_sets(results_dir=results_dir)
            )
            or "none"
        )
        raise LookupError(f"Unknown result set {set_id!r}; known ids: {known}")
    return ResultSet.from_dict(_read_json(path))


def latest_runs_by_case(*, results_dir: Path = RESULTS_DIR) -> list[RunRecord]:
    """For every case, the runs of the newest saved set that ran it."""
    seen: set[str] = set()
    latest: list[RunRecord] = []
    for row in list_result_sets(results_dir=results_dir):
        runs = load_result_set(row["set_id"], results_dir=results_dir).runs
        fresh = [run for run in runs if run.case_id not in seen]
        latest += fresh
        seen |= {run.case_id for run in fresh}
    return latest


def summarise(runs: list[RunRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[RunRecord]] = {}
    for run in runs:
        groups.setdefault((run.harness, run.case_id), []).append(run)
    rows = []
    for (harness, case_id), group in groups.items():
        failing: dict[str, int] = {}
        for run in group:
            for check in run.checks:
                if not check["passed"]:
                    failing[check["name"]] = failing.get(check["name"], 0) + 1
        rows.append(
            {
                "harness": harness,
                "case_id": case_id,
                "runs": len(group),
                "passed": sum(1 for run in group if run.passed),
                "pass_rate": _pass_rate(group),
                "errors": sum(1 for run in group if run.error),
                "failing_checks": failing,
                "mean_input_tokens": sum(run.input_tokens for run in group)
                / len(group),
            }
        )
    return sorted(rows, key=lambda row: (row["case_id"], row["harness"]))


def _rates_by_key(
    runs: list[RunRecord], by: str
) -> dict[tuple[str, ...], float | None]:
    groups: dict[tuple[str, ...], list[RunRecord]] = {}
    for run in runs:
        key = (run.case_id,) if by == "case" else (run.harness, run.case_id)
        groups.setdefault(key, []).append(run)
    return {key: _pass_rate(group) for key, group in groups.items()}


def _status(baseline: float | None, current: float | None) -> str:
    if baseline is None or current is None or current == baseline:
        return "same"
    return "regression" if current < baseline else "improvement"


def diff_runs(
    baseline: list[RunRecord],
    current: list[RunRecord],
    *,
    by: Literal["harness_case", "case"] = "harness_case",
) -> list[dict[str, Any]]:
    if by not in ("harness_case", "case"):
        raise ValueError(f"by must be 'harness_case' or 'case', got {by!r}")
    before = _rates_by_key(baseline, by)
    after = _rates_by_key(current, by)
    rows = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        status = (
            "new"
            if key not in before
            else "missing"
            if key not in after
            else _status(old, new)
        )
        fields = (
            {"case_id": key[0]}
            if by == "case"
            else {"harness": key[0], "case_id": key[1]}
        )
        delta = None if old is None or new is None else new - old
        rows.append(
            {
                **fields,
                "baseline_rate": old,
                "current_rate": new,
                "delta": delta,
                "status": status,
            }
        )
    return sorted(rows, key=lambda row: (row["case_id"], row.get("harness", "")))
