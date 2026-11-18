"""Facts a security policy needs about an action (Session 5 onwards).

This module does not decide anything. It collects, deterministically and
outside the model, the facts an authorization policy needs: who is acting,
on what, whether the target is critical, whether the trading session is open
and which approval (if any) backs the request. The policy itself (RBAC,
freeze rules, approval requirements) is written in the harness.

    from meridian.security import describe_action

    request = describe_action(ctx.deps, "rollback_change", "CHG-4471", confirmation_ref)
    if request.critical and request.trading_session and request.approver_role != "incident-manager":
        return {"status": "refused", "reason": "..."}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from meridian.agent_runtime import IncidentDeps


@dataclass(frozen=True)
class ActionRequest:
    action: str
    target: str
    component: str | None  # None when the target does not exist
    critical: bool
    role: str  # role of the identity the agent acts as
    actor: str
    trading_session: bool
    time: str
    confirmation_ref: str | None
    approval_status: str | None  # approved | denied | None (no approval found)
    approver_role: str | None
    approval_matches: bool  # the approval is for this action and this target

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_action(
    deps: IncidentDeps, action: str, target: str, confirmation_ref: str | None = None
) -> ActionRequest:
    sim = deps.sim
    state = sim.state
    component = None
    try:
        if action == "restart_instance":
            component = state.instance(target)[0]
        elif action == "restart_service":
            component = state.component(target)
        elif action == "rollback_change":
            component = state.component(state.change(target).component)
    except KeyError:
        component = None

    approval = next(
        (
            record
            for record in sim.approvals
            if record["approval_ref"] == confirmation_ref
        ),
        None,
    )
    return ActionRequest(
        action=action,
        target=target,
        component=component.name if component else None,
        critical=bool(component and component.critical),
        role=deps.identity["role"],
        actor=deps.identity["name"],
        trading_session=sim.clock.is_trading_session(state.tick),
        time=sim.clock.timestamp(state.tick),
        confirmation_ref=confirmation_ref,
        approval_status=approval["status"] if approval else None,
        approver_role=approval["approver_role"] if approval else None,
        approval_matches=bool(
            approval and approval["action"] == action and approval["target"] == target
        ),
    )
