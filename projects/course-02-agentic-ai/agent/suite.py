"""Run the full team over a case set and prepare what the loop needs around it.

A run goes through the workbench's `compare` and lands in a saved result set, so every number in
the lineage resolves through `results show`. A candidate is staged as a throwaway copy of the
harness folder, with the candidate's version file pinned for its role.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from agent.versions import ROLES, Role, RoleVersion, TeamVersion, load_team

from app import commands
from app.core.model_budget import BudgetExhaustedError
from app.core.results import ResultSet, load_result_set
from app.core.runner import RunRecord
from app.core.team_trace import TrustedFacts
from app.paths import CHECKS_DIR, HARNESSES_DIR, RESULTS_DIR

HARNESS_NAME = "project/team"
Arm = Literal["baseline", "candidate"]
Side = Literal["train", "valid", "test"]


@dataclass(frozen=True)
class CompareRequest:
    """One team run over a case set: which team (a harness folder), which cases, how many times."""

    label: str
    arm: Arm
    split: Side
    case_ids: list[str]
    reps: int
    harnesses_dir: Path


Compare = Callable[[CompareRequest], ResultSet]


def workbench_compare(
    model: Any, *, results_dir: Path = RESULTS_DIR, max_workers: int = 4
) -> Compare:
    """The real compare: the workbench's matrix runner and saved result sets."""

    def compare(request: CompareRequest) -> ResultSet:
        outcome = commands.compare(
            [HARNESS_NAME],
            request.case_ids,
            reps=request.reps,
            model=model,
            max_workers=max_workers,
            save_label=request.label,
            harnesses_dir=request.harnesses_dir,
            results_dir=results_dir,
        )
        saved = load_result_set(outcome["result_set"], results_dir=results_dir)
        raise_if_budget_exhausted(saved.runs)
        return saved

    return compare


def raise_if_budget_exhausted(records: Sequence[RunRecord]) -> None:
    """The matrix turns a raised exception into an errored record; the cap must still stop the loop."""
    for record in records:
        if record.error and "BudgetExhaustedError" in record.error:
            raise BudgetExhaustedError(record.error)


# Staging ---------------------------------------------------------------------------------------


def _write_team_file(destination: Path, source: Path, pins: Mapping[Role, str]) -> None:
    team = yaml.safe_load(source.read_text(encoding="utf-8"))
    team["versions"] = {**team["versions"], **pins}
    destination.write_text(yaml.safe_dump(team, sort_keys=False), encoding="utf-8")


@contextmanager
def staged_team(
    harnesses_dir: Path = HARNESSES_DIR,
    *,
    team_file: Path | None = None,
    pins: Mapping[Role, str] | None = None,
    override: RoleVersion | None = None,
) -> Iterator[Path]:
    """A temporary harness folder that runs one team, leaving the real folder untouched.

    `team_file` names another team.yaml (its versions sit beside it); `pins` pick other versions
    of the pinned roles; `override` adds a candidate's version file and pins it for its role.
    """
    source_team = team_file or harnesses_dir / "team.yaml"
    source_versions = source_team.parent / "versions"
    chosen: dict[Role, str] = dict(pins or {})
    if override is not None:
        chosen[override.role] = override.version
    with tempfile.TemporaryDirectory(prefix="team-stage-") as directory:
        staged = Path(directory) / "harnesses"
        (staged / "versions").mkdir(parents=True)
        shutil.copy2(harnesses_dir / "team.py", staged / "team.py")
        _write_team_file(staged / "team.yaml", source_team, chosen)
        for role in ROLES:
            shutil.copytree(source_versions / role, staged / "versions" / role)
        if override is not None:
            write_version_file(staged / "versions", override)
        yield staged


class _VersionDumper(yaml.SafeDumper):
    """Multi-line text as a literal block, so instructions stay readable in the file."""


def _represent_text(dumper: yaml.SafeDumper, text: str) -> yaml.ScalarNode:
    style = "|" if "\n" in text else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


_VersionDumper.add_representer(str, _represent_text)


def version_text(version: RoleVersion) -> str:
    content = version.model_dump(
        include={
            "instructions",
            "tools",
            "max_requests",
            "max_tool_calls",
            "verify_recovery",
        }
    )
    return yaml.dump(content, Dumper=_VersionDumper, sort_keys=False, width=100)


def write_version_file(versions_dir: Path, version: RoleVersion) -> Path:
    """Write `versions/<role>/<version>.yaml` atomically; an existing file is never replaced."""
    directory = versions_dir / version.role
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{version.version}.yaml"
    with tempfile.NamedTemporaryFile(
        "w",
        dir=directory,
        prefix=f".{version.version}-",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as partial:
        partial.write(version_text(version))
        partial_path = Path(partial.name)
    try:
        # A hard link fails when the name is taken, so two loops cannot both claim one version.
        target.hardlink_to(partial_path)
    finally:
        partial_path.unlink()
    return target


def next_version(versions_dir: Path, role: Role) -> str:
    numbers = [
        int(path.stem.removeprefix("v"))
        for path in (versions_dir / role).glob("v*.yaml")
        if path.stem.removeprefix("v").isdigit()
    ]
    return f"v{max(numbers, default=0) + 1}"


def team_pins(team: TeamVersion) -> dict[str, str]:
    return {role: version.version for role, version in team.roles.items()}


def load_staged_fingerprint(staged: Path) -> str:
    return load_team(staged / "team.yaml").fingerprint


# Trusted facts ---------------------------------------------------------------------------------


def _components(solution: Mapping[str, Any], scenario: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    recovery = solution.get("recovery") or {}
    for condition in recovery.get("conditions", []):
        if "component" in condition:
            names.append(str(condition["component"]))
        if "link" in condition:
            names.extend(str(condition["link"]).split("->"))
    for fault in scenario.get("faults", []):
        names.extend(str(fault[key]) for key in ("component", "source") if key in fault)
    return list(dict.fromkeys(name.strip() for name in names))


def _recovered(record: RunRecord, solution: Mapping[str, Any]) -> bool | None:
    """None when the case states no recovery expectation, so the reviewer is not judged on it."""
    for check in record.checks:
        if str(check["name"]).startswith("recovery held"):
            return bool(check["passed"])
    expected = (solution.get("report") or {}).get("claims_recovery")
    if expected is None:
        return None
    return bool(expected)


def trusted_facts(record: RunRecord, *, checks_dir: Path = CHECKS_DIR) -> TrustedFacts:
    """Simulator and solution facts for one run, read from the case files, never from the agents."""
    solution_path = checks_dir / f"{record.case_id}.yaml"
    solution = yaml.safe_load(solution_path.read_text(encoding="utf-8")) or {}
    scenario = yaml.safe_load(Path(record.case_path).read_text(encoding="utf-8")) or {}
    return TrustedFacts(
        affected_components=_components(solution, scenario),
        recovered=_recovered(record, solution),
    )
