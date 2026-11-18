"""State of the Meridian Exchange: components, instances, links and changes.

The simulator only keeps numbers. There are no real machines: every metric,
log line and alert is derived from this state by `meridian.signals`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"
TOPOLOGY_FILE = DATA_DIR / "topology.yaml"

BASELINE_MEMORY_PCT = 55.0
BASELINE_CPU_PCT = 30.0
BASELINE_DISK_PCT = 40.0
BASE_ERROR_RATE = 0.001
RESTART_TICKS = 2


@dataclass
class Instance:
    instance_id: str
    status: str = "running"  # running | restarting | isolated
    memory_pct: float = BASELINE_MEMORY_PCT
    cpu_pct: float = BASELINE_CPU_PCT
    restart_ticks_left: int = 0
    restarts: int = 0
    latency_ms: float = 0.0
    error_rate: float = BASE_ERROR_RATE


@dataclass
class Component:
    name: str
    critical: bool
    version: str
    instances: list[Instance]
    base_latency_ms: float
    depends_on: list[str]
    inflow_per_tick: int = 0
    capacity_per_tick: int = 0
    disk_pct: float = BASELINE_DISK_PCT
    latency_ms: float = 0.0
    error_rate: float = BASE_ERROR_RATE
    queue_depth: float = 0.0
    site: str | None = None  # active site, when the scenario gives the component sites

    def running_instances(self) -> list[Instance]:
        return [instance for instance in self.instances if instance.status == "running"]

    @property
    def running_count(self) -> int:
        return len(self.running_instances())


@dataclass
class Link:
    source: str
    target: str
    state: str = "up"  # up | degraded | down
    extra_latency_ms: float = 0.0


@dataclass
class Change:
    change_id: str
    component: str
    kind: str  # deploy | config | firewall_patch
    description: str
    at: int
    version_before: str | None = None
    version_after: str | None = None
    active: bool = True
    rolled_back_at: int | None = None


@dataclass
class ExchangeState:
    tick: int
    components: dict[str, Component]
    links: dict[tuple[str, str], Link]
    changes: list[Change] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    trading_open: str = "09:00"
    trading_close: str = "17:30"

    def component(self, name: str) -> Component:
        if name not in self.components:
            raise KeyError(f"Unknown component: {name}")
        return self.components[name]

    def instance(self, instance_id: str) -> tuple[Component, Instance]:
        for component in self.components.values():
            for instance in component.instances:
                if instance.instance_id == instance_id:
                    return component, instance
        raise KeyError(f"Unknown instance: {instance_id}")

    def link(self, source: str, target: str) -> Link:
        if (source, target) not in self.links:
            raise KeyError(f"No link from {source} to {target}")
        return self.links[(source, target)]

    def change(self, change_id: str) -> Change:
        for change in self.changes:
            if change.change_id == change_id:
                return change
        raise KeyError(f"Unknown change: {change_id}")

    def copy(self) -> ExchangeState:
        return copy.deepcopy(self)


def load_topology(
    path: Path = TOPOLOGY_FILE, overrides: dict[str, Any] | None = None
) -> ExchangeState:
    """Build the initial state from the topology file and optional overrides."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    overrides = overrides or {}
    component_overrides = overrides.get("components", {})

    components: dict[str, Component] = {}
    for name, spec in data["components"].items():
        spec = {**spec, **component_overrides.get(name, {})}
        instances = [
            Instance(instance_id=f"{name}-{index}")
            for index in range(1, int(spec["instances"]) + 1)
        ]
        components[name] = Component(
            name=name,
            critical=bool(spec["critical"]),
            version=str(spec["version"]),
            instances=instances,
            base_latency_ms=float(spec["base_latency_ms"]),
            depends_on=list(spec.get("depends_on", [])),
            inflow_per_tick=int(spec.get("inflow_per_tick", 0)),
            capacity_per_tick=int(spec.get("capacity_per_tick", 0)),
            latency_ms=float(spec["base_latency_ms"]),
        )

    links = {
        (name, dependency): Link(source=name, target=dependency)
        for name, component in components.items()
        for dependency in component.depends_on
    }
    changes = [Change(**entry) for entry in data.get("history", [])]
    calendar = data.get("calendar", {})
    return ExchangeState(
        tick=0,
        components=components,
        links=links,
        changes=changes,
        trading_open=calendar.get("trading_open", "09:00"),
        trading_close=calendar.get("trading_close", "17:30"),
    )
