"""Step a case through the simulator without an agent and record what an agent could observe."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from meridian.simulator import Simulator

FAULT_COMMON_KEYS = ("fault_id", "kind", "at", "until", "change_id")


@dataclass
class Frame:
    tick: int
    time: str
    trading_session: bool
    components: dict[str, dict[str, Any]]
    links: list[dict[str, Any]]
    logs: list[dict[str, Any]]
    alerts_open: list[dict[str, Any]]
    alerts_opened: list[dict[str, Any]]
    tickets_new: list[dict[str, Any]]
    events: list[dict[str, Any]]
    active_faults: list[dict[str, Any]]
    active_changes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


@dataclass
class Exploration:
    case_id: str
    title: str
    brief: dict[str, Any]
    topology: list[dict[str, Any]]
    warmup_logs: list[dict[str, Any]]
    frames: list[Frame]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "brief": copy.deepcopy(self.brief),
            "topology": copy.deepcopy(self.topology),
            "warmup_logs": copy.deepcopy(self.warmup_logs),
            "frames": [frame.to_dict() for frame in self.frames],
        }


def _describe_fault(index: int, fault: Any) -> dict[str, Any]:
    fields = asdict(fault)
    return {"index": index, **fields}


def _describe_change(change: Any) -> dict[str, Any]:
    return {
        "change_id": change.change_id,
        "component": change.component,
        "kind": change.kind,
        "description": change.description,
        "at": change.at,
        "active": change.active,
        "rolled_back": change.rolled_back_at is not None,
    }


def _capture_frame(sim: Simulator, *, first: bool) -> Frame:
    state = sim.state
    tick = state.tick
    # Tickets seeded before the first tick are already visible at frame 0.
    ticket_is_new = (
        (lambda created: created <= tick)
        if first
        else (lambda created: created == tick)
    )
    return Frame(
        tick=tick,
        time=sim.clock.label(tick),
        trading_session=sim.clock.is_trading_session(tick),
        components=copy.deepcopy(sim.snapshot()["components"]),
        links=[
            {
                "source": link.source,
                "target": link.target,
                "state": link.state,
                "extra_latency_ms": link.extra_latency_ms,
            }
            for link in state.links.values()
        ],
        logs=[dict(line) for line in sim.logs.lines if line["tick"] == tick],
        alerts_open=[
            alert.public() for alert in sim.alerts.alerts if alert.state == "open"
        ],
        alerts_opened=[
            alert.public() for alert in sim.alerts.alerts if alert.opened_tick == tick
        ],
        tickets_new=[
            t.public(with_comments=False)
            for t in sim.tickets.tickets
            if ticket_is_new(t.created_tick)
        ],
        events=[
            copy.deepcopy(event) for event in state.events if event["tick"] == tick
        ],
        active_faults=[
            _describe_fault(i, f)
            for i, f in enumerate(sim.faults, start=1)
            if f.is_active(state)
        ],
        active_changes=[_describe_change(change) for change in state.changes],
    )


def _topology(sim: Simulator) -> list[dict[str, Any]]:
    return [
        {
            "name": component.name,
            "critical": component.critical,
            "depends_on": list(component.depends_on),
            "instances": [instance.instance_id for instance in component.instances],
        }
        for component in sim.state.components.values()
    ]


def explore(case_path: Path, ticks: int) -> Exploration:
    if ticks < 0:
        raise ValueError(f"ticks must be >= 0, got {ticks}")
    sim = Simulator(case_path)
    first_tick = sim.state.tick
    brief = sim.incident_brief()
    warmup_logs = [dict(line) for line in sim.logs.lines if line["tick"] < first_tick]
    frames = [_capture_frame(sim, first=True)]
    for _ in range(ticks):
        sim.advance(1)
        frames.append(_capture_frame(sim, first=False))
    return Exploration(
        case_id=sim.scenario.scenario_id,
        title=sim.scenario.title,
        brief=brief,
        topology=_topology(sim),
        warmup_logs=warmup_logs,
        frames=frames,
    )
