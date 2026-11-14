"""Discover the cases (scenarios with their checks) and the harnesses of the project."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from app.paths import CASES_DIR, CHECKS_DIR, HARNESSES_DIR, SESSIONS_DIR

SESSION_PREFIX = re.compile(r"^(s\d{2})-")
PROJECT_SESSION = "project"


@dataclass
class CaseInfo:
    case_id: str
    title: str
    path: Path
    check_path: Path | None
    incident_id: str
    incident_summary: str
    seed: int
    session: str
    # Scenario file modification time, so callers can tell when a cached simulation is stale.
    modified: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "path": str(self.path),
            "check_path": str(self.check_path) if self.check_path else None,
            "incident_id": self.incident_id,
            "incident_summary": self.incident_summary,
            "seed": self.seed,
            "session": self.session,
            "modified": self.modified,
        }


@dataclass
class HarnessInfo:
    name: str
    path: Path
    source: Literal["project", "session"]
    read_only: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "source": self.source,
            "read_only": self.read_only,
        }


def _session_of(case_id: str) -> str:
    match = SESSION_PREFIX.match(case_id)
    return match.group(1) if match else PROJECT_SESSION


def _read_case(path: Path, checks_dir: Path) -> CaseInfo:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "id" not in data:
        raise ValueError(f"{path}: scenario file has no top-level 'id'")
    case_id = str(data["id"])
    incident = data.get("incident") or {}
    check_path = checks_dir / f"{case_id}.yaml"
    return CaseInfo(
        case_id=case_id,
        title=str(data.get("title", "")),
        path=path,
        check_path=check_path if check_path.is_file() else None,
        incident_id=str(incident.get("id", "")),
        incident_summary=str(incident.get("summary", "")),
        seed=int(data.get("seed", 1)),
        session=_session_of(case_id),
        modified=path.stat().st_mtime,
    )


def list_cases(
    *, cases_dir: Path = CASES_DIR, checks_dir: Path = CHECKS_DIR
) -> list[CaseInfo]:
    cases = [_read_case(path, checks_dir) for path in sorted(cases_dir.glob("*.yaml"))]
    return sorted(cases, key=lambda case: case.case_id)


def get_case(
    case_id: str, *, cases_dir: Path = CASES_DIR, checks_dir: Path = CHECKS_DIR
) -> CaseInfo:
    cases = list_cases(cases_dir=cases_dir, checks_dir=checks_dir)
    for case in cases:
        if case.case_id == case_id:
            return case
    known = ", ".join(case.case_id for case in cases)
    raise LookupError(f"unknown case {case_id!r}; known: {known}")


def case_text(
    case_id: str, *, cases_dir: Path = CASES_DIR, checks_dir: Path = CHECKS_DIR
) -> dict[str, Any]:
    case = get_case(case_id, cases_dir=cases_dir, checks_dir=checks_dir)
    check = case.check_path.read_text(encoding="utf-8") if case.check_path else None
    return {"scenario": case.path.read_text(encoding="utf-8"), "check": check}


def list_harnesses(
    *, harnesses_dir: Path = HARNESSES_DIR, sessions_dir: Path = SESSIONS_DIR
) -> list[HarnessInfo]:
    project = [
        HarnessInfo(f"project/{path.stem}", path, "project", False)
        for path in sorted(harnesses_dir.glob("*.py"))
        if not path.name.startswith("_")
    ]
    sessions = [
        HarnessInfo(f"{path.parents[1].name}/{path.stem}", path, "session", True)
        for path in sorted(sessions_dir.glob("*/starter/harness*.py"))
    ]
    return project + sorted(sessions, key=lambda harness: harness.name)


def get_harness(
    name: str, *, harnesses_dir: Path = HARNESSES_DIR, sessions_dir: Path = SESSIONS_DIR
) -> HarnessInfo:
    harnesses = list_harnesses(harnesses_dir=harnesses_dir, sessions_dir=sessions_dir)
    for harness in harnesses:
        if harness.name == name:
            return harness
    known = ", ".join(harness.name for harness in harnesses)
    raise LookupError(f"unknown harness {name!r}; known: {known}")
