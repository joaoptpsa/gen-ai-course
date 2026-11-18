"""Actions that change the simulated exchange, and the executor that runs them.

The executor is supplied infrastructure. It:

- applies the effect of each action to the state;
- keeps an audit log (who, what, when, with which approval, outcome);
- remembers idempotency keys: the same key with the same content returns the
  recorded action without a new effect, the same key with different content is
  rejected as a conflict;
- rejects actions on critical components without a valid approval;
- can drop the response of an action after applying it, when a scenario asks
  for it, to simulate a timeout with an unknown result.

`isolate_instance` takes one instance out of service until it is restarted.
`failover` targets `<component>:<site>` and moves the component to one of the
standby sites its scenario defines; a site with `fails: true` refuses the move.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from meridian.faults import ChangeFault, ResourceFault
from meridian.model import BASELINE_CPU_PCT, BASELINE_MEMORY_PCT, RESTART_TICKS

if TYPE_CHECKING:
    from meridian.simulator import Simulator

ACTIONS = (
    "restart_instance",
    "restart_service",
    "rollback_change",
    "isolate_instance",
    "failover",
)


def split_failover_target(target: str) -> tuple[str, str]:
    """`order-gateway:C` -> ("order-gateway", "C")."""
    name, separator, site = target.partition(":")
    if not separator or not site:
        raise ValueError(f"Failover target {target!r} must be <component>:<site>.")
    return name, site


class ActionTimeout(Exception):
    """The executor did not answer. The action may or may not have been applied."""


@dataclass
class ActionRecord:
    action_id: str
    tick: int
    time: str
    action: str
    target: str
    actor: str
    outcome: str  # completed | rejected | already_applied | conflict
    detail: str
    effect_applied: bool
    idempotency_key: str | None = None
    confirmation_ref: str | None = None
    trading_session: bool = False

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("effect_applied")
        data.pop("trading_session")
        return data


class ActionExecutor:
    def __init__(self, sim: Simulator) -> None:
        self.sim = sim
        self.audit: list[ActionRecord] = []
        self._by_key: dict[str, ActionRecord] = {}
        self._calls: Counter[str] = Counter()

    def _record(
        self,
        action: str,
        target: str,
        outcome: str,
        detail: str,
        effect: bool,
        key: str | None,
        actor: str,
        confirmation_ref: str | None,
    ) -> ActionRecord:
        tick = self.sim.state.tick
        record = ActionRecord(
            action_id=f"ACT-{len(self.audit) + 1:03d}",
            tick=tick,
            time=self.sim.clock.label(tick),
            action=action,
            target=target,
            actor=actor,
            outcome=outcome,
            detail=detail,
            effect_applied=effect,
            idempotency_key=key,
            confirmation_ref=confirmation_ref,
            trading_session=self.sim.clock.is_trading_session(tick),
        )
        self.audit.append(record)
        return record

    def _target_component(self, action: str, target: str):
        state = self.sim.state
        if action in ("restart_instance", "isolate_instance"):
            component, _ = state.instance(target)
            return component
        if action == "restart_service":
            return state.component(target)
        if action == "rollback_change":
            return state.component(state.change(target).component)
        if action == "failover":
            name, site = split_failover_target(target)
            component = state.component(name)
            config = self.sim.scenario.sites.get(name)
            if config is None:
                raise ValueError(f"{name} has no standby site to fail over to.")
            if site != config["primary"] and site not in (config.get("standby") or {}):
                raise ValueError(f"Unknown site {site!r} for {name}.")
            return component
        raise ValueError(f"Unknown action: {action}")

    def execute(
        self,
        action: str,
        target: str,
        *,
        idempotency_key: str | None = None,
        actor: str = "agent",
        confirmation_ref: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key is not None and idempotency_key in self._by_key:
            previous = self._by_key[idempotency_key]
            if (previous.action, previous.target) == (action, target):
                self._record(
                    action,
                    target,
                    "already_applied",
                    f"Same key as {previous.action_id}; no new effect.",
                    False,
                    idempotency_key,
                    actor,
                    confirmation_ref,
                )
                return {**previous.public(), "status": "already_applied"}
            record = self._record(
                action,
                target,
                "conflict",
                f"Key already used by {previous.action_id} for {previous.action} {previous.target}.",
                False,
                idempotency_key,
                actor,
                confirmation_ref,
            )
            return {**record.public(), "status": "conflict"}

        try:
            component = self._target_component(action, target)
        except (KeyError, ValueError) as error:
            record = self._record(
                action,
                target,
                "rejected",
                str(error).strip("'\""),
                False,
                idempotency_key,
                actor,
                confirmation_ref,
            )
            return {**record.public(), "status": "rejected"}

        if component.critical and not self.sim.approval_valid(
            confirmation_ref, action, target
        ):
            record = self._record(
                action,
                target,
                "rejected",
                f"{component.name} is a critical component: a valid approval for this action and target is required.",
                False,
                idempotency_key,
                actor,
                confirmation_ref,
            )
            return {**record.public(), "status": "rejected"}

        detail, effect = self._apply(action, target)
        record = self._record(
            action,
            target,
            "completed",
            detail,
            effect,
            idempotency_key,
            actor,
            confirmation_ref,
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = record

        self._calls[action] += 1
        for drop in self.sim.scenario.executor.get("drop_response", []):
            if (
                drop.get("action") == action
                and int(drop.get("call", 1)) == self._calls[action]
            ):
                raise ActionTimeout(
                    f"No response from the executor for {action} {target} (timeout). The action may or may not have been applied."
                )
        return {**record.public(), "status": "completed"}

    def _restart(self, instance_id: str) -> None:
        state = self.sim.state
        component, instance = state.instance(instance_id)
        instance.status = "restarting"
        instance.restart_ticks_left = RESTART_TICKS
        instance.restarts += 1
        instance.memory_pct = BASELINE_MEMORY_PCT
        instance.cpu_pct = BASELINE_CPU_PCT
        for fault in self.sim.faults:
            if (
                isinstance(fault, ResourceFault)
                and fault.instance == instance_id
                and fault.resource == "cpu"
            ):
                fault.until = state.tick
            if isinstance(fault, ChangeFault):
                fault.stuck.discard(instance_id)
        state.events.append(
            {
                "tick": state.tick + 1,
                "type": "instance_restart",
                "component": component.name,
                "instance": instance_id,
            }
        )

    def _apply(self, action: str, target: str) -> tuple[str, bool]:
        """Apply an action. Returns its detail and whether it changed the state."""
        state = self.sim.state
        if action == "restart_instance":
            self._restart(target)
            return f"Instance {target} is restarting.", True
        if action == "restart_service":
            for instance in state.component(target).instances:
                self._restart(instance.instance_id)
            return f"All instances of {target} are restarting.", True
        if action == "isolate_instance":
            return self._isolate(target)
        if action == "failover":
            return self._failover(target)
        change = state.change(target)
        if not change.active:
            return "No effect: change already rolled back.", False
        change.active = False
        change.rolled_back_at = state.tick
        if change.kind == "deploy" and change.version_before:
            state.component(change.component).version = change.version_before
        return f"Change {target} rolled back on {change.component}.", True

    def _isolate(self, instance_id: str) -> tuple[str, bool]:
        state = self.sim.state
        component, instance = state.instance(instance_id)
        if instance.status == "isolated":
            return f"No effect: {instance_id} is already isolated.", False
        instance.status = "isolated"
        instance.restart_ticks_left = 0
        state.events.append(
            {
                "tick": state.tick,
                "type": "instance_isolated",
                "component": component.name,
                "instance": instance_id,
            }
        )
        return (
            f"Instance {instance_id} taken out of service; restart_instance brings it back.",
            True,
        )

    def _failover(self, target: str) -> tuple[str, bool]:
        state = self.sim.state
        name, site = split_failover_target(target)
        component = state.component(name)
        if component.site == site:
            return f"No effect: {name} already runs on site {site}.", False
        standby = (self.sim.scenario.sites[name].get("standby") or {}).get(site) or {}
        if standby.get("fails"):
            reason = standby.get("reason", "the switchover did not complete")
            return (
                f"Failover of {name} to site {site} failed: {reason}. {name} stays on site {component.site}.",
                False,
            )
        previous = component.site
        component.site = site
        for instance in component.instances:
            if instance.status != "isolated":
                self._restart(instance.instance_id)
        state.events.append(
            {
                "tick": state.tick,
                "type": "failover",
                "component": name,
                "from": previous,
                "to": site,
            }
        )
        return f"{name} is failing over from site {previous} to site {site}.", True

    def status(self, idempotency_key: str) -> dict[str, Any]:
        record = self._by_key.get(idempotency_key)
        if record is None:
            return {
                "idempotency_key": idempotency_key,
                "status": "unknown_key",
                "detail": "No action was registered with this key.",
            }
        return {**record.public(), "status": record.outcome}

    def effects(
        self, action: str | None = None, target: str | None = None
    ) -> list[ActionRecord]:
        return [
            record
            for record in self.audit
            if record.effect_applied
            and (action is None or record.action == action)
            and (target is None or record.target == target)
        ]
