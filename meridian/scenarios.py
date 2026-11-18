"""Scenario files.

A scenario describes what happens: initial state, faults, extra log lines,
alerts, tickets, the identity the agent runs as, MCP server settings and
memories from earlier shifts. It never contains the expected answer. Solutions (root
cause, recovery conditions, forbidden actions) live in separate files that the
agent never reads; see `meridian.evaluate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Scenario:
    scenario_id: str
    title: str
    incident: dict[str, Any]
    seed: int = 1
    start_time: str = "10:00"
    warmup_ticks: int = 10
    ticks_per_action: int = 1
    background_log_lines: int = 3
    initial: dict[str, Any] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)
    faults: list[dict[str, Any]] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    tools: dict[str, Any] = field(default_factory=dict)
    executor: dict[str, Any] = field(default_factory=dict)
    approvals: list[str] = field(default_factory=list)
    date: str = "2026-11-04"
    actor: dict[str, Any] = field(
        default_factory=lambda: {"role": "first-line", "name": "agent-first-line"}
    )
    approver: dict[str, Any] = field(default_factory=lambda: {"mode": "approve_all"})
    mcp: dict[str, Any] = field(default_factory=dict)
    memory_seed: list[dict[str, Any]] = field(default_factory=list)
    # {component: {primary: A, standby: {B: {error_rate, latency_ms, reason, fails}}}}: what failover can do
    sites: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["scenario_id"] = data.pop("id")
    return Scenario(**data, path=path)


def load_solution(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
