"""Project requirements, their evidence cases and their status from run results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from app.paths import REQUIREMENTS_FILE

GROUPS = ("capability", "execution", "criterion", "deliverable")
REQUIRED_KEYS = ("id", "group", "title", "description", "evidence", "notes")

Status = Literal["no_evidence", "untested", "failing", "passing"]


@dataclass
class Requirement:
    id: str
    group: str
    title: str
    description: str
    evidence: list[str]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequirementStatus:
    requirement: Requirement
    status: Status
    cases: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "status": self.status,
            "cases": [dict(case) for case in self.cases],
        }


def _parse_deadline(raw: Any) -> datetime:
    deadline = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if deadline.tzinfo is None:
        return deadline.replace(tzinfo=timezone.utc)
    return deadline


def _parse_item(raw: Any, position: int) -> Requirement:
    if not isinstance(raw, dict):
        raise ValueError(f"requirements item #{position} is not a mapping")  # noqa: TRY004
    name = raw.get("id", f"#{position}")
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise ValueError(
            f"requirements item {name!r} is missing keys: {', '.join(missing)}"
        )
    if raw["group"] not in GROUPS:
        raise ValueError(
            f"requirements item {name!r} has unknown group {raw['group']!r}; known: {', '.join(GROUPS)}"
        )
    if not isinstance(raw["evidence"], list):
        raise ValueError(f"requirements item {name!r} has non-list evidence")  # noqa: TRY004
    return Requirement(
        id=str(raw["id"]),
        group=raw["group"],
        title=str(raw["title"]),
        description=str(raw["description"]),
        evidence=[str(case) for case in raw["evidence"]],
        notes=str(raw["notes"] or ""),
    )


def load_requirements(
    *, path: Path = REQUIREMENTS_FILE
) -> tuple[datetime, list[Requirement]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "deadline" not in data or "items" not in data:
        raise ValueError(f"{path} must be a mapping with 'deadline' and 'items'")
    items = [
        _parse_item(raw, position)
        for position, raw in enumerate(data["items"], start=1)
    ]
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise ValueError(f"requirements item {item.id!r} is duplicated")
        seen.add(item.id)
    return _parse_deadline(data["deadline"]), items


def save_requirements(
    deadline: datetime, items: list[Requirement], *, path: Path = REQUIREMENTS_FILE
) -> None:
    data = {
        "deadline": deadline.isoformat(),
        "items": [
            {key: item.to_dict()[key] for key in REQUIRED_KEYS} for item in items
        ],
    }
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _case_summary(case_id: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        run
        for run in runs
        if run["case_id"] == case_id and run.get("passed") is not None
    ]
    passed = sum(1 for run in evaluated if run["passed"])
    pass_rate = passed / len(evaluated) if evaluated else None
    return {
        "case_id": case_id,
        "runs": len(evaluated),
        "passed": passed,
        "pass_rate": pass_rate,
    }


def _status_of(cases: list[dict[str, Any]]) -> Status:
    if not cases:
        return "no_evidence"
    if any(case["passed"] < case["runs"] for case in cases):
        return "failing"
    if any(case["runs"] == 0 for case in cases):
        return "untested"
    return "passing"


def requirement_status(
    items: list[Requirement], runs: list[dict[str, Any]]
) -> list[RequirementStatus]:
    statuses = []
    for item in items:
        cases = [_case_summary(case_id, runs) for case_id in item.evidence]
        statuses.append(
            RequirementStatus(requirement=item, status=_status_of(cases), cases=cases)
        )
    return statuses


def time_left(deadline: datetime, now: datetime | None = None) -> timedelta:
    return deadline - (now or datetime.now(timezone.utc))


def _edit(item_id: str, path: Path, change: Any) -> Requirement:
    deadline, items = load_requirements(path=path)
    matches = [item for item in items if item.id == item_id]
    if not matches:
        raise LookupError(
            f"unknown requirement {item_id!r}; known: {', '.join(item.id for item in items)}"
        )
    item = matches[0]
    change(item)
    save_requirements(deadline, items, path=path)
    return item


def set_note(item_id: str, text: str, *, path: Path = REQUIREMENTS_FILE) -> Requirement:
    def change(item: Requirement) -> None:
        item.notes = text

    return _edit(item_id, path, change)


def add_evidence(
    item_id: str, case_id: str, *, path: Path = REQUIREMENTS_FILE
) -> Requirement:
    def change(item: Requirement) -> None:
        if case_id not in item.evidence:
            item.evidence.append(case_id)

    return _edit(item_id, path, change)


def remove_evidence(
    item_id: str, case_id: str, *, path: Path = REQUIREMENTS_FILE
) -> Requirement:
    def change(item: Requirement) -> None:
        if case_id not in item.evidence:
            raise ValueError(
                f"requirement {item_id!r} has no evidence case {case_id!r}"
            )
        item.evidence.remove(case_id)

    return _edit(item_id, path, change)
