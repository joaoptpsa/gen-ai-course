"""Fault mechanisms.

Scenarios are built from a few well-implemented mechanisms, combined and
parameterised, rather than from many independent behaviours:

- `link`: cut or degrade the connection between two components;
- `resource`: consume memory, CPU or disk on one instance;
- `change`: a deploy or configuration change with a harmful effect while it
  stays active (rolled back with `rollback_change`);
- `data`: delay or corrupt the data a component produces;
- `noise`: duplicated alerts and false positives (signals only).

A fault linked to a change (`change_id`) stops when that change is rolled back,
or, with `trigger: rolled_back`, starts only then. A fault with `site` applies
only while its component runs on that site (see the scenario's `sites`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from meridian.model import ExchangeState


@dataclass
class Effect:
    component: str
    error_rate: float = 0.0
    latency_ms: float = 0.0
    reason: str = "internal error"
    instance: str | None = None  # only this instance; otherwise the whole component


@dataclass
class Fault:
    fault_id: str
    kind: str
    at: int
    change_id: str | None = None
    until: int | None = None
    trigger: str = "active"  # active: while the change is active | rolled_back: once it is rolled back
    site: str | None = None

    def scope_component(self, state: ExchangeState) -> str | None:
        """The component whose site decides whether a site-bound fault applies."""
        return None

    def is_active(self, state: ExchangeState) -> bool:
        if state.tick < self.at:
            return False
        if self.until is not None and state.tick >= self.until:
            return False
        if self.site is not None:
            name = self.scope_component(state)
            if name is None or state.component(name).site != self.site:
                return False
        if self.change_id is None:
            return True
        try:
            change_active = state.change(self.change_id).active
        except KeyError:
            return False
        if self.trigger == "rolled_back":
            return not change_active
        return change_active


@dataclass
class LinkFault(Fault):
    source: str = ""
    target: str = ""
    mode: str = "down"  # down | degraded
    extra_latency_ms: float = 0.0

    def scope_component(self, state: ExchangeState) -> str | None:
        return self.source


@dataclass
class ResourceFault(Fault):
    instance: str = ""
    resource: str = "memory"  # memory | cpu | disk
    rate: float = 1.0
    start_value: float | None = None
    started: bool = False

    def scope_component(self, state: ExchangeState) -> str | None:
        component, _ = state.instance(self.instance)
        return component.name


@dataclass
class ChangeFault(Fault):
    effects: list[Effect] = field(default_factory=list)
    # sticky: an instance the change reached keeps the effect after the rollback, until it restarts.
    sticky: bool = False
    stuck: set[str] = field(default_factory=set)

    def scope_component(self, state: ExchangeState) -> str | None:
        return self.effects[0].component if self.effects else None


@dataclass
class DataFault(Fault):
    component: str = "market-data"
    delay_ms: float = 0.0
    corrupt: bool = False

    def scope_component(self, state: ExchangeState) -> str | None:
        return self.component


@dataclass
class NoiseFault(Fault):
    noise: str = "duplicate_alerts"  # duplicate_alerts | false_positive
    component: str = "order-gateway"
    count: int = 1
    rule: str = "latency_high"

    def scope_component(self, state: ExchangeState) -> str | None:
        return self.component


def build_fault(index: int, spec: dict[str, Any]) -> Fault:
    """Create a fault from a scenario entry."""
    spec = dict(spec)
    kind = spec.pop("type")
    at = int(spec.pop("at", 0))
    fault_id = spec.pop("fault_id", f"F{index:02d}")
    common = {
        "fault_id": fault_id,
        "kind": kind,
        "at": at,
        "change_id": spec.pop("change_id", None),
        "until": spec.pop("until", None),
        "trigger": spec.pop("trigger", "active"),
        "site": spec.pop("site", None),
    }
    if kind == "link":
        return LinkFault(**common, **spec)
    if kind == "resource":
        return ResourceFault(**common, **spec)
    if common["trigger"] == "rolled_back" and common["change_id"] is None:
        raise ValueError(f"Fault {fault_id}: trigger rolled_back needs a change_id")
    if kind == "change":
        effects = [Effect(**effect) for effect in spec.pop("effects", [])]
        return ChangeFault(**common, effects=effects, **spec)
    if kind == "data":
        return DataFault(**common, **spec)
    if kind == "noise":
        return NoiseFault(**common, **spec)
    raise ValueError(f"Unknown fault type: {kind}")
