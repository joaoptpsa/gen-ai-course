"""The Meridian Exchange simulator.

`Simulator` loads a scenario, simulates the ticks before the agent starts
(warm-up), and then advances a fixed number of ticks for every agent action.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path
from typing import Any

from meridian import rules
from meridian.actions import ActionExecutor
from meridian.clock import SimClock, parse_hhmm
from meridian.faults import ChangeFault, Fault, NoiseFault, build_fault
from meridian.model import Change, ExchangeState, load_topology
from meridian.scenarios import Scenario, load_scenario
from meridian.signals import AlertStore, LogStore, MetricStore, TicketStore


class Simulator:
    def __init__(self, scenario: Scenario | str | Path) -> None:
        if not isinstance(scenario, Scenario):
            scenario = load_scenario(scenario)
        self.scenario = scenario
        self.rng = random.Random(scenario.seed)
        self.state: ExchangeState = load_topology(overrides=scenario.initial)
        self.clock = SimClock(
            start_minutes=parse_hhmm(scenario.start_time) - scenario.warmup_ticks,
            trading_open=parse_hhmm(self.state.trading_open),
            trading_close=parse_hhmm(self.state.trading_close),
            start_date=scenario.date
            if isinstance(scenario.date, date)
            else date.fromisoformat(str(scenario.date)),
        )
        self.faults: list[Fault] = [
            build_fault(index, spec)
            for index, spec in enumerate(scenario.faults, start=1)
        ]
        self.metrics = MetricStore()
        self.logs = LogStore(
            rng=self.rng, background_per_tick=scenario.background_log_lines
        )
        self.alerts = AlertStore()
        self.tickets = TicketStore()
        self.executor = ActionExecutor(self)
        self._pending_changes = sorted(
            scenario.changes, key=lambda change: change["at"]
        )
        self._applied_noise: set[str] = set()
        self.approvals: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        for entry in scenario.tickets:
            if entry["at"] < 1:
                self.tickets.add(entry, entry["at"], self.clock)

        self.metrics.record(self.state, self.clock)
        self.advance(scenario.warmup_ticks)
        self.agent_start_tick = self.state.tick

    # Time ---------------------------------------------------------------

    def advance(self, ticks: int = 1) -> None:
        for _ in range(ticks):
            self._step(self.state.tick + 1)

    def agent_action(self) -> None:
        self.advance(self.scenario.ticks_per_action)

    def _step(self, tick: int) -> None:
        state = self.state
        state.tick = tick
        while self._pending_changes and self._pending_changes[0]["at"] <= tick:
            spec = dict(self._pending_changes.pop(0))
            change = Change(**spec)
            state.changes.append(change)
            if change.kind == "deploy" and change.version_after:
                state.component(change.component).version = change.version_after

        rules.step(state, self.faults, tick)

        for entry in self.scenario.alerts:
            if entry["at"] == tick:
                self.alerts.open_alert(
                    entry["rule"],
                    entry["component"],
                    tick,
                    self.clock,
                    entry.get("instance"),
                    auto_resolve=entry.get("auto_resolve", True),
                )
        for entry in self.scenario.tickets:
            if entry["at"] == tick:
                self.tickets.add(entry, tick, self.clock)
        self._apply_noise(tick)

        self.logs.generate(state, self.clock, self._active_reasons())
        for entry in self.scenario.logs:
            if entry["at"] == tick:
                self.logs.add(
                    state,
                    self.clock,
                    entry["component"],
                    entry.get("level", "INFO"),
                    entry["message"],
                    entry.get("instance"),
                )
        self.alerts.evaluate(state, self.clock)
        self.metrics.record(state, self.clock)

    def _active_reasons(self) -> dict[str, str]:
        reasons: dict[str, str] = {}
        for fault in self.faults:
            if isinstance(fault, ChangeFault) and fault.is_active(self.state):
                for effect in fault.effects:
                    reasons[effect.component] = effect.reason
        return reasons

    def _apply_noise(self, tick: int) -> None:
        for fault in self.faults:
            if (
                not isinstance(fault, NoiseFault)
                or fault.fault_id in self._applied_noise
                or fault.at > tick
            ):
                continue
            self._applied_noise.add(fault.fault_id)
            for _ in range(fault.count):
                self.alerts.open_alert(
                    fault.rule, fault.component, tick, self.clock, auto_resolve=False
                )

    # Approvals and outbound messages ---------------------------------------

    def request_approval(
        self,
        action: str,
        target: str,
        reason: str,
        approver_role: str,
        requested_by: str,
    ) -> dict[str, Any]:
        """Ask a (simulated) human to approve one action on one target.

        The scenario's `approver` decides the answer: `approve_all` (the
        default: the approver accepts what the agent asks), `deny_all`, or
        `approve_roles: [...]` (only those approver roles answer yes).
        An approval is valid for that action and target only.
        """
        policy = self.scenario.approver
        mode = policy.get("mode", "approve_all")
        if mode == "deny_all":
            approved = False
        elif "approve_roles" in policy:
            approved = approver_role in policy["approve_roles"]
        else:
            approved = True
        record = {
            "approval_ref": f"APR-{len(self.approvals) + 1:03d}",
            "action": action,
            "target": target,
            "reason": reason,
            "approver_role": approver_role,
            "requested_by": requested_by,
            "time": self.clock.label(self.state.tick),
            "tick": self.state.tick,
            "status": "approved" if approved else "denied",
        }
        self.approvals.append(record)
        return dict(record)

    def approval_valid(self, ref: str | None, action: str, target: str) -> bool:
        if ref is None:
            return False
        if ref in self.scenario.approvals:
            return True
        return any(
            record["approval_ref"] == ref
            and record["status"] == "approved"
            and record["action"] == action
            and record["target"] == target
            for record in self.approvals
        )

    def send_message(self, channel: str, text: str, author: str) -> dict[str, Any]:
        message = {
            "message_id": f"MSG-{len(self.outbox) + 1:03d}",
            "channel": channel,
            "text": text,
            "author": author,
            "time": self.clock.label(self.state.tick),
            "tick": self.state.tick,
        }
        self.outbox.append(message)
        return {
            "message_id": message["message_id"],
            "channel": channel,
            "status": "sent",
        }

    # Information for the agent's first message ---------------------------

    def incident_brief(self) -> dict[str, Any]:
        incident = self.scenario.incident
        alert_id = None
        rule, _, component = str(incident.get("alert", "")).partition("/")
        if rule:
            candidates = [
                alert
                for alert in self.alerts.alerts
                if alert.rule == rule and alert.component == component
            ]
            if candidates:
                alert_id = candidates[0].alert_id
        return {
            "incident_id": incident["id"],
            "summary": incident["summary"],
            "alert_id": alert_id,
            "time": self.clock.label(self.state.tick),
            "tick": self.state.tick,
        }

    def snapshot(self) -> dict[str, Any]:
        """Current metrics for every component (for the CLI and the trainer)."""
        return self.metrics.history[-1]
