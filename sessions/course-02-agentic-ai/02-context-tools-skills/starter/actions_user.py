"""Exercise 3 — Actions that are safe to repeat.

The problem
    The agent restarts order-gateway-2. The restart happens, but the answer
    never arrives: a timeout. The agent does what any program does on an error:
    it tries again. The instance restarted twice, and every member connected
    to it lost its session twice.

    The same happens when the model simply asks twice, restarts a healthy
    instance "just in case", or restarts the whole service because an old
    runbook says so. The model will make these mistakes. Your tools must make
    them harmless.

Build, in this file: a layer around the actions, with four rules
    1. One intent, one key. Every action carries an idempotency_key derived from
       the intent (incident, action, target), not chosen by the model.
    2. Ask before acting, and after a lost answer. If the intent was already
       carried out, report it instead of acting. After a timeout, ask the
       executor what happened instead of trying again.
    3. Act only if the reason still holds. restart_instance restarts only while
       the instance's memory is above 90 % (or it is not running); otherwise it
       refuses and says why.
    4. Dry run for the whole service. restart_service does nothing without an
       explicit confirmation argument; it answers with what it would do and the
       impact (every member session on the service is dropped).

What the executor gives you (ctx.deps.tools)
    - restart_instance / restart_service / rollback_change(..., idempotency_key=key):
      the same key returns the earlier action without a new effect;
    - action_status(key): "completed", or "unknown_key" if it never arrived;
    - a lost answer comes back as {"error": "... timeout ...", "retryable": False}.

Watch out
    - A key written by the model can change between two calls: the protection is gone.
    - "No answer" is not "nothing happened". Find out; do not guess.
    - When a rule blocks an action, the model reads your answer: say what was
      blocked, why, and what to do instead.
    - Your key will block a legitimate second restart in the same incident. Think about when that is wrong.

Hints (read only if stuck)
    1. The key: f"{incident_id}:{action}:{target}", with incident_id = ctx.deps.sim.scenario.incident["id"].
    2. One helper used by the three actions: guarded(deps, action, target, execute).
       Check action_status(key); if completed, return "already done"; otherwise
       execute with the key; on a timeout, check action_status(key) again and report it.
    3. Memory of one instance: ctx.deps.tools.read_metrics(component, 1, per_instance=True)
       gives each instance with memory_pct and status.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import RunContext

from meridian.agent_runtime import IncidentDeps

MEMORY_LIMIT_PCT = 90
CRITICAL_COMPONENTS = ("matching-engine", "reference-db")
DONE_STATUSES = ("completed", "already_applied")
# A leak that returns after this many restarts in one incident needs a person, not another restart.
MAX_ATTEMPTS = 3

Execute = Callable[[str], dict[str, Any]]


def intent_key(deps: IncidentDeps, action: str, target: str, attempt: int = 1) -> str:
    """Name an intent by incident, action and target; a justified repeat gets its own attempt number."""
    key = f"{deps.sim.scenario.incident['id']}:{action}:{target}"
    if attempt > 1:
        key = f"{key}:{attempt}"
    return key


def attempts_done(deps: IncidentDeps, action: str, target: str) -> int | None:
    """Count the attempts at this intent the executor completed, or None when it cannot be asked."""
    done = 0
    while done < MAX_ATTEMPTS:
        known = deps.tools.action_status(intent_key(deps, action, target, done + 1))
        status = known.get("status")
        if status is None:
            return None
        if status not in DONE_STATUSES:
            return done
        done += 1
    return done


def refused(detail: str, instead: str) -> dict[str, Any]:
    return {"status": "refused", "detail": detail, "instead": instead}


def already_done(key: str, action: str, target: str) -> dict[str, Any]:
    return {
        "status": "already_done",
        "idempotency_key": key,
        "detail": f"{action} on {target} was already carried out in this incident. It was not repeated.",
        "instead": "Use wait_for_recovery to see its effect.",
    }


def unknown_status() -> dict[str, Any]:
    return refused(
        "The executor did not answer whether this action was already carried out. Nothing was done.",
        "Call the same tool again shortly. Do not reach the same effect through another tool.",
    )


def guarded(deps: IncidentDeps, action: str, target: str, key: str, execute: Execute) -> dict[str, Any]:
    """Execute once under the intent's key; when the answer is lost, ask the executor what happened."""
    result = execute(key)
    if "error" not in result:
        return {**result, "idempotency_key": key}

    # No answer is not "nothing happened": the executor's record decides.
    known = deps.tools.action_status(key)
    status = known.get("status")
    if status in DONE_STATUSES:
        return {
            **known,
            "lost_answer": result["error"],
            "detail": f"The answer was lost, but the executor confirms {action} on {target} was applied. Do not repeat it.",
        }
    if status == "unknown_key":
        return {
            "status": "not_applied",
            "idempotency_key": key,
            "lost_answer": result["error"],
            "detail": f"The executor has no record of {action} on {target}: nothing was applied. Calling again is safe.",
        }
    return {
        "status": "unknown",
        "idempotency_key": key,
        "lost_answer": result["error"],
        "detail": f"Neither {action} nor its status answered. Call the same tool again: it looks the action up before acting.",
    }


def instance_state(deps: IncidentDeps, component: str, instance_id: str) -> dict[str, Any]:
    """Read the latest status and memory of one instance, or an error."""
    metrics = deps.tools.read_metrics(component, 1, per_instance=True)
    if "error" in metrics:
        return metrics
    instances = metrics["readings"][-1]["instances"]
    if instance_id not in instances:
        return {"error": f"{component} has no instance {instance_id}; it has {', '.join(instances)}"}
    return instances[instance_id]


def restart_instance(ctx: RunContext[IncidentDeps], instance_id: str) -> dict[str, Any]:
    """Restart one instance, e.g. order-gateway-2, only while its memory is above 90 %.

    A repeated request in the same incident is reported, not repeated.
    """
    deps = ctx.deps
    action = "restart_instance"
    component = instance_id.rsplit("-", 1)[0]
    if component in CRITICAL_COMPONENTS:
        return refused(f"{component} is a critical component; this agent does not restart it.", "Report it as the root cause and escalate.")

    state = instance_state(deps, component, instance_id)
    if "error" in state:
        return refused(f"Cannot check {instance_id} before restarting it: {state['error']}", "Check the instance id, or try again if metrics were unavailable.")
    done = attempts_done(deps, action, instance_id)
    if done is None:
        return unknown_status()

    restarting = state["status"] != "running"
    justified = not restarting and state["memory_pct"] > MEMORY_LIMIT_PCT
    if done and not justified:
        return already_done(intent_key(deps, action, instance_id, done), action, instance_id)
    if restarting:
        return refused(f"{instance_id} is already restarting. Another restart would add nothing.", "Use wait_for_recovery.")
    if not justified:
        return refused(
            f"{instance_id} is running with memory at {state['memory_pct']} %, not above {MEMORY_LIMIT_PCT} %. A restart is not justified.",
            "Look for another cause: recent changes, links, other instances.",
        )
    if done >= MAX_ATTEMPTS:
        return refused(f"{instance_id} was restarted {done} times in this incident and the memory keeps rising.", "Report the leak as the root cause and escalate.")

    key = intent_key(deps, action, instance_id, done + 1)
    return guarded(deps, action, instance_id, key, lambda key: deps.tools.restart_instance(instance_id, idempotency_key=key))


def service_preview(deps: IncidentDeps, component: str) -> dict[str, Any]:
    """Describe what a whole-service restart would do, without doing it."""
    metrics = deps.tools.read_metrics(component, 1, per_instance=True)
    if "error" in metrics:
        return refused(f"Cannot preview restarting {component}: {metrics['error']}", "Check the component name.")
    instances = metrics["readings"][-1]["instances"]
    return {
        "status": "dry_run",
        "would_restart": {instance_id: f"{state['status']}, memory {state['memory_pct']} %" for instance_id, state in instances.items()},
        "impact": f"Every open member session on {component} is dropped, on every instance at once.",
        "instead": "Restart only the unhealthy instance with restart_instance. Call restart_service with confirm=true only if every instance needs it.",
    }


def restart_service(ctx: RunContext[IncidentDeps], component: str, confirm: bool = False) -> dict[str, Any]:
    """Preview restarting every instance of a component; it acts only with confirm=true.

    Every open member session on the component is dropped. Prefer restart_instance.
    """
    deps = ctx.deps
    action = "restart_service"
    if component in CRITICAL_COMPONENTS:
        return refused(f"{component} is a critical component; this agent does not restart it.", "Report it as the root cause and escalate.")

    done = attempts_done(deps, action, component)
    if done is None:
        return unknown_status()
    if done:
        return already_done(intent_key(deps, action, component), action, component)
    if not confirm:
        return service_preview(deps, component)

    key = intent_key(deps, action, component)
    return guarded(deps, action, component, key, lambda key: deps.tools.restart_service(component, idempotency_key=key))


def rollback_change(ctx: RunContext[IncidentDeps], change_id: str) -> dict[str, Any]:
    """Roll back a deployment or configuration change, e.g. CHG-4310, once per incident.

    Changes on matching-engine or reference-db are refused: report them as the root cause.
    """
    deps = ctx.deps
    action = "rollback_change"
    done = attempts_done(deps, action, change_id)
    if done is None:
        return unknown_status()
    if done:
        return already_done(intent_key(deps, action, change_id), action, change_id)

    key = intent_key(deps, action, change_id)
    result = guarded(deps, action, change_id, key, lambda key: deps.tools.rollback_change(change_id, idempotency_key=key))
    if result.get("status") == "rejected" and "critical component" in str(result.get("detail")):
        result["instead"] = "Report this change as the root cause. This agent does not change critical components; do not ask for an approval."
    return result


# Only these functions are offered to the model. The helpers above run in Python.
TOOLS = (restart_instance, restart_service, rollback_change)
