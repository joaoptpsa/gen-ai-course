"""Propagation rules applied on every tick.

The rules turn faults and actions into consistent symptoms. Cascades are not
written one by one: a cut link raises the client's error rate, failed requests
fill the queue, and a long queue raises latency.
"""

from __future__ import annotations

from meridian.faults import ChangeFault, DataFault, Fault, LinkFault, ResourceFault
from meridian.model import (
    BASE_ERROR_RATE,
    BASELINE_CPU_PCT,
    BASELINE_MEMORY_PCT,
    Component,
    ExchangeState,
)

MEMORY_LATENCY_THRESHOLD = 85.0
MEMORY_LATENCY_FACTOR = 40.0
MEMORY_ERROR_THRESHOLD = 97.0
CPU_LATENCY_THRESHOLD = 90.0
CPU_LATENCY_MS = 300.0
DEPENDENCY_DOWN_ERROR = 0.4
DEPENDENCY_DOWN_LATENCY_MS = 150.0
UNHEALTHY_DEPENDENCY_ERROR = 0.3
QUEUE_LATENCY_FACTOR = 0.1


def dependency_order(state: ExchangeState) -> list[str]:
    """Components ordered so that dependencies are processed first."""
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in ordered:
            return
        for dependency in state.components[name].depends_on:
            visit(dependency)
        ordered.append(name)

    for name in state.components:
        visit(name)
    return ordered


def _apply_resource_fault(state: ExchangeState, fault: ResourceFault) -> None:
    component, instance = state.instance(fault.instance)
    if fault.resource == "disk":
        if not fault.started:
            component.disk_pct = (
                fault.start_value
                if fault.start_value is not None
                else component.disk_pct
            )
            fault.started = True
        component.disk_pct = min(100.0, component.disk_pct + fault.rate)
        return
    if instance.status != "running":
        return
    if fault.resource == "memory":
        if not fault.started and fault.start_value is not None:
            instance.memory_pct = fault.start_value
        fault.started = True
        instance.memory_pct = min(100.0, instance.memory_pct + fault.rate)
    elif fault.resource == "cpu":
        fault.started = True
        instance.cpu_pct = fault.start_value if fault.start_value is not None else 95.0


def _advance_instances(state: ExchangeState) -> None:
    for component in state.components.values():
        for instance in component.instances:
            if instance.status == "restarting":
                instance.restart_ticks_left -= 1
                if instance.restart_ticks_left <= 0:
                    instance.status = "running"
                    state.events.append(
                        {
                            "tick": state.tick,
                            "type": "instance_ready",
                            "component": component.name,
                            "instance": instance.instance_id,
                        }
                    )


def _crash_if_out_of_memory(state: ExchangeState) -> None:
    for component in state.components.values():
        for instance in component.instances:
            if instance.status == "running" and instance.memory_pct >= 100.0:
                instance.status = "restarting"
                instance.restart_ticks_left = 2
                instance.restarts += 1
                instance.memory_pct = BASELINE_MEMORY_PCT
                instance.cpu_pct = BASELINE_CPU_PCT
                state.events.append(
                    {
                        "tick": state.tick,
                        "type": "instance_crash",
                        "component": component.name,
                        "instance": instance.instance_id,
                    }
                )


def _instance_health(component: Component) -> None:
    for instance in component.instances:
        latency = component.base_latency_ms
        error = BASE_ERROR_RATE
        if instance.status != "running":
            instance.latency_ms = 0.0
            instance.error_rate = 1.0
            continue
        if instance.memory_pct > MEMORY_LATENCY_THRESHOLD:
            latency += (
                instance.memory_pct - MEMORY_LATENCY_THRESHOLD
            ) * MEMORY_LATENCY_FACTOR
        if instance.memory_pct > MEMORY_ERROR_THRESHOLD:
            error += 0.2
        if instance.cpu_pct > CPU_LATENCY_THRESHOLD:
            latency += CPU_LATENCY_MS
        instance.latency_ms = latency
        instance.error_rate = error


def step(state: ExchangeState, faults: list[Fault], tick: int) -> None:
    """Advance the state to `tick` and apply every rule once."""
    state.tick = tick
    _advance_instances(state)

    for link in state.links.values():
        link.state = "up"
        link.extra_latency_ms = 0.0

    active = [fault for fault in faults if fault.is_active(state)]
    for fault in active:
        if isinstance(fault, ResourceFault):
            _apply_resource_fault(state, fault)
        elif isinstance(fault, LinkFault):
            link = state.link(fault.source, fault.target)
            link.state = fault.mode
            link.extra_latency_ms = fault.extra_latency_ms
    for fault in faults:
        if (
            isinstance(fault, ResourceFault)
            and fault.resource == "cpu"
            and not fault.is_active(state)
        ):
            component, instance = state.instance(fault.instance)
            if fault.started and instance.cpu_pct > BASELINE_CPU_PCT:
                instance.cpu_pct = BASELINE_CPU_PCT
    _crash_if_out_of_memory(state)

    for name in dependency_order(state):
        component = state.components[name]
        _instance_health(component)
        running = component.running_instances()
        if not running:
            component.latency_ms = component.base_latency_ms + 1000.0
            component.error_rate = 1.0
        else:
            component.latency_ms = sum(
                instance.latency_ms for instance in running
            ) / len(running)
            component.error_rate = sum(
                instance.error_rate for instance in running
            ) / len(running)

        for dependency in component.depends_on:
            link = state.link(name, dependency)
            target = state.components[dependency]
            if link.state == "down" or not target.running_instances():
                component.error_rate += DEPENDENCY_DOWN_ERROR
                component.latency_ms += DEPENDENCY_DOWN_LATENCY_MS
            else:
                if link.state == "degraded":
                    component.latency_ms += link.extra_latency_ms
                if target.error_rate > UNHEALTHY_DEPENDENCY_ERROR:
                    component.error_rate += 0.15

        for fault in active:
            if isinstance(fault, ChangeFault):
                for effect in fault.effects:
                    if effect.component == name:
                        component.error_rate += effect.error_rate
                        component.latency_ms += effect.latency_ms
            elif isinstance(fault, DataFault) and fault.component == name:
                component.latency_ms += fault.delay_ms
                if fault.corrupt:
                    component.error_rate += 0.05

        component.error_rate = max(0.0, min(1.0, component.error_rate))

        if component.inflow_per_tick:
            share = len(running) / len(component.instances)
            processed = (
                component.capacity_per_tick * share * (1.0 - component.error_rate)
            )
            component.queue_depth = max(
                0.0, component.queue_depth + component.inflow_per_tick - processed
            )
            component.latency_ms += component.queue_depth * QUEUE_LATENCY_FACTOR

        component.latency_ms = round(component.latency_ms, 1)
        component.error_rate = round(component.error_rate, 4)
        component.queue_depth = round(component.queue_depth, 1)
