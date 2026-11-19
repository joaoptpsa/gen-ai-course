"""Team versions: which version file each role uses, and the topology.

A version file holds only what a proposer may change: the instructions, the subset of the role's
tools, the request and tool limits, and whether remediation verifies recovery before it reports
"resolved". Permissions, handoff contracts and the reviewer's access to real state stay in code.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["orchestrator", "network", "database", "remediation", "reviewer"]
Topology = Literal["orchestrator", "pipeline"]
ROLES: tuple[Role, ...] = (
    "orchestrator",
    "network",
    "database",
    "remediation",
    "reviewer",
)

ROLE_TOOL_CATALOG: dict[Role, tuple[str, ...]] = {
    "orchestrator": ("ask_network", "ask_database", "ask_remediation", "ask_reviewer"),
    "network": (
        "read_metrics",
        "read_logs",
        "check_link",
        "recent_changes",
        "exchange_status",
    ),
    "database": (
        "read_metrics",
        "read_logs",
        "search_tickets",
        "read_ticket",
        "recent_changes",
    ),
    "remediation": (
        "read_metrics",
        "read_logs",
        "recent_changes",
        "exchange_status",
        "action_status",
        "rollback_change",
        "restart_instance",
        "isolate_instance",
        "failover",
    ),
    "reviewer": ("read_metrics", "read_logs", "check_link", "exchange_status"),
}
# The reviewer must keep reading real state, and the orchestrator must keep asking the reviewer.
REQUIRED_TOOLS: dict[Role, tuple[str, ...]] = {
    "orchestrator": ("ask_reviewer",),
    "network": (),
    "database": (),
    "remediation": (),
    "reviewer": ("read_metrics",),
}

MAX_REQUESTS_CEILING = 40
MAX_TOOL_CALLS_CEILING = 30
VERSION_ID = re.compile(r"^v[0-9]+$")

HARNESSES_DIR = Path(__file__).resolve().parents[1] / "harnesses"


class RoleVersionFile(BaseModel):
    """The fields a version file may hold."""

    model_config = ConfigDict(extra="forbid")

    instructions: str = Field(min_length=1)
    tools: list[str]
    max_requests: int = Field(ge=1, le=MAX_REQUESTS_CEILING)
    max_tool_calls: int = Field(ge=0, le=MAX_TOOL_CALLS_CEILING)
    verify_recovery: bool = False


class RoleVersion(RoleVersionFile):
    """A version file resolved for one role."""

    role: Role
    version: str

    @model_validator(mode="after")
    def check_against_role(self) -> RoleVersion:
        catalog = ROLE_TOOL_CATALOG[self.role]
        unknown = [name for name in self.tools if name not in catalog]
        if unknown:
            raise ValueError(f"{self.role} has no tools {unknown}; catalog: {catalog}")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError(f"{self.role} lists a tool twice")
        missing = [name for name in REQUIRED_TOOLS[self.role] if name not in self.tools]
        if missing:
            raise ValueError(f"{self.role} must keep the tools {missing}")
        if self.verify_recovery and self.role != "remediation":
            raise ValueError("verify_recovery applies to remediation only")
        return self


class TeamFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology: Topology
    versions: dict[Role, str]

    @model_validator(mode="after")
    def check_roles(self) -> TeamFile:
        missing = [role for role in ROLES if role not in self.versions]
        if missing:
            raise ValueError(f"team.yaml pins no version for {missing}")
        for role, version in self.versions.items():
            if not VERSION_ID.match(version):
                raise ValueError(f"{role}: version {version!r} must look like v1")
        return self


class TeamVersion(BaseModel):
    """One resolved team: the topology and one version per role."""

    topology: Topology
    roles: dict[Role, RoleVersion]

    @property
    def fingerprint(self) -> str:
        """A content hash of the resolved configuration, stable across file layout."""
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _read_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected a mapping")
    return data


def load_role_version(versions_dir: Path, role: Role, version: str) -> RoleVersion:
    if not VERSION_ID.match(version):
        raise ValueError(f"{role}: version {version!r} must look like v1")
    path = (versions_dir / role / f"{version}.yaml").resolve()
    if not path.is_relative_to(versions_dir.resolve() / role):
        raise ValueError(f"{path}: outside the {role} version directory")
    content = RoleVersionFile.model_validate(_read_yaml(path))
    return RoleVersion(role=role, version=version, **content.model_dump())


def load_team(path: Path, *, override: RoleVersion | None = None) -> TeamVersion:
    """Resolve `team.yaml`; `override` replaces one role's version (a candidate under test)."""
    team = TeamFile.model_validate(_read_yaml(path))
    versions_dir = path.parent / "versions"
    roles: dict[Role, RoleVersion] = {
        role: load_role_version(versions_dir, role, team.versions[role])
        for role in ROLES
    }
    if override is not None:
        # Revalidate: an override built with model_construct must still obey the role's rules.
        roles[override.role] = RoleVersion.model_validate(override.model_dump())
    return TeamVersion(topology=team.topology, roles=roles)
