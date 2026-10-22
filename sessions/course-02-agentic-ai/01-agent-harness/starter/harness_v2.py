"""Session 1: the first-line incident agent, with tools to investigate and one action.

The agent reads the alert, finds the runbook for the alerted component and
follows its steps with the tools below. It can restart one instance of a
non-critical component, and a check in code only accepts "resolved" when the
metrics meet the runbook's recovery criterion.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext

from meridian.agent_runtime import IncidentDeps
from meridian.tools import MeridianTools

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Investigate the incident, follow the applicable runbook and fix the problem when it allows.

1. Read the alert. List the runbooks and read the one for the alerted component.
2. Follow the runbook steps in order with your tools. When the data points to one instance, name it.
3. Base every conclusion on tool results and cite them in evidence (metric source_ref, log ref).
   Never estimate a value you could not read. If a tool you need keeps failing, say so, take no
   action and report "insufficient_information".
4. Your only action is restarting one instance of a non-critical component, and only when the
   runbook calls for it. Never restart the same instance twice.
5. Report "resolved" only when metrics read after any action meet the runbook's recovery
   criterion. A completed restart or a closed alert is not proof of recovery.
"""

# Recovery criteria from the runbooks: every metric must stay below its limit.
RECOVERY_CRITERIA: dict[str, dict[str, float]] = {
    "order-gateway": {"latency_ms": 20.0, "error_rate": 0.01},
    "market-data": {"latency_ms": 10.0},
}
RECOVERY_READINGS = 3


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["resolved", "unresolved", "insufficient_information"]
    diagnosis: str
    affected_instance: str | None = None
    actions_taken: list[str] = []
    proposed_mitigation: str | None = None
    evidence: list[str]


# Tools -------------------------------------------------------------------
# A tool is a Python function. The model sees its name, its arguments and its
# docstring, and receives what it returns. `ctx.deps.tools` gives access to
# the simulator (see meridian/tools.py for what it offers).


def read_alert(ctx: RunContext[IncidentDeps], alert_id: str) -> dict[str, Any]:
    """Read an alert: rule, component, instance, state (open or resolved) and when it was opened.

    Args:
        alert_id: The alert's id, such as ALR-1001.
    """
    return ctx.deps.tools.read_alert(alert_id)


def list_alerts(
    ctx: RunContext[IncidentDeps], component: str | None = None
) -> dict[str, Any]:
    """List the open alerts. Instance alerts such as memory_pressure name the instance.

    Args:
        component: Only list the alerts of this component, such as order-gateway. Omit it to list them all.
    """
    return ctx.deps.tools.list_alerts(component=component)


def read_metrics_with_retry(
    tools: MeridianTools, component: str, window_ticks: int
) -> dict[str, Any]:
    """Read per-instance metrics, retrying once when the backend reports a transient failure."""
    result = tools.read_metrics(component, window_ticks, per_instance=True)
    if not result.get("retryable"):
        return result
    return tools.read_metrics(component, window_ticks, per_instance=True)


def read_metrics(
    ctx: RunContext[IncidentDeps], component: str, window_ticks: int = 5
) -> dict[str, Any]:
    """Read a component's recent metrics, with the values of each instance.

    A result with "error" means the metrics backend did not answer: there are no values to use.

    Args:
        component: One of order-gateway, matching-engine, market-data, settlement, reference-db.
        window_ticks: How many of the last minutes to read, 1 to 30.
    """
    return read_metrics_with_retry(ctx.deps.tools, component, window_ticks)


def read_logs(
    ctx: RunContext[IncidentDeps],
    component: str,
    level: str | None = None,
    contains: str | None = None,
) -> dict[str, Any]:
    """Read the 30 most recent log lines of a component.

    Args:
        component: The component whose logs to read, such as order-gateway.
        level: Only read lines of this level: INFO, WARN or ERROR.
        contains: Only read lines whose message contains this text, ignoring case.
    """
    return ctx.deps.tools.read_logs(
        component=component, level=level, contains=contains, limit=30
    )


def check_link(
    ctx: RunContext[IncidentDeps], source: str, target: str
) -> dict[str, Any]:
    """Check the connection from a component to one of its dependencies: up, degraded or down.

    Dependencies: order-gateway -> reference-db, matching-engine; matching-engine -> market-data;
    settlement -> matching-engine, reference-db.

    Args:
        source: The component whose connection to check, such as order-gateway.
        target: The dependency it connects to, such as reference-db.
    """
    return ctx.deps.tools.check_link(source, target)


def recent_changes(ctx: RunContext[IncidentDeps], component: str) -> dict[str, Any]:
    """List a component's latest deploys and configuration changes, newest first.

    `as_of` is the date and time of this answer; `minutes_ago` is how long before it each change happened.

    Args:
        component: The component whose changes to list, such as order-gateway.
    """
    sim = ctx.deps.sim
    as_of_tick = sim.state.tick
    result = ctx.deps.tools.recent_changes(component=component)
    if "changes" not in result:
        return result
    # Alerts and metrics show only the time of day, so the date and age tell a deploy from days ago apart from one minutes ago.
    changes = [
        {**change, "minutes_ago": as_of_tick - change["at_tick"]}
        for change in result["changes"]
    ]
    return {**result, "as_of": sim.clock.timestamp(as_of_tick), "changes": changes}


def list_runbooks(ctx: RunContext[IncidentDeps]) -> dict[str, Any]:
    """List the runbooks: name, version and the component versions each one applies to."""
    return ctx.deps.tools.list_runbooks()


def read_runbook(ctx: RunContext[IncidentDeps], name: str) -> dict[str, Any]:
    """Read the latest version of a runbook.

    Args:
        name: The runbook's name, as list_runbooks gives it.
    """
    return ctx.deps.tools.read_runbook(name)


def restart_instance(ctx: RunContext[IncidentDeps], instance_id: str) -> dict[str, Any]:
    """Restart one instance. It is back after about 2 minutes.

    Instances of critical components (matching-engine, reference-db) are rejected.

    Args:
        instance_id: The instance to restart, such as order-gateway-2.
    """
    return ctx.deps.tools.restart_instance(instance_id)


# Checks ------------------------------------------------------------------
# The output validator runs on every report. Raising ModelRetry rejects the
# report and sends the reason back to the model, which must answer again.


def last_restart_tick(tools: MeridianTools) -> int | None:
    """The tick of the latest restart the executor did not reject, or None when there was none."""
    ticks = [
        call.tick
        for call in tools.trace
        if call.tool == "restart_instance" and call.result.get("status") != "rejected"
    ]
    return max(ticks, default=None)


def check_recovery(
    ctx: RunContext[IncidentDeps], report: IncidentReport
) -> IncidentReport:
    """Accept "resolved" only when metrics read here meet the runbook's recovery criterion."""
    if report.status != "resolved":
        return report
    tools = ctx.deps.tools
    alert = tools.read_alert(ctx.deps.sim.incident_brief()["alert_id"])
    if "error" in alert:
        raise ModelRetry(
            f'The incident alert cannot be read ({alert["error"]}), so recovery cannot be confirmed. Do not report "resolved".'
        )
    component: str = alert["component"]
    limits = RECOVERY_CRITERIA.get(component)
    if limits is None:
        raise ModelRetry(
            f'No recovery criterion is known for {component}, so recovery cannot be confirmed. Report "unresolved".'
        )
    metrics = read_metrics_with_retry(tools, component, RECOVERY_READINGS)
    if "error" in metrics:
        raise ModelRetry(
            f'The metrics of {component} cannot be read ({metrics["error"]}), so recovery cannot be confirmed. Do not report "resolved".'
        )
    restart_tick = last_restart_tick(tools)
    readings = [
        reading
        for reading in metrics["readings"]
        if restart_tick is None or reading["tick"] > restart_tick
    ]
    if len(readings) < RECOVERY_READINGS:
        raise ModelRetry(
            f"Only {len(readings)} reading(s) of {component} were taken after the restart and the runbook needs {RECOVERY_READINGS}. Read the metrics again, then report."
        )
    breaches = [
        f"{reading['time']} {metric}={reading[metric]} (limit {limit})"
        for reading in readings
        for metric, limit in limits.items()
        if reading[metric] >= limit
    ]
    if breaches:
        raise ModelRetry(
            f'{component} has not recovered: {"; ".join(breaches)}. Report "unresolved".'
        )
    return report


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(
        model,
        deps_type=IncidentDeps,
        output_type=IncidentReport,
        instructions=INSTRUCTIONS,
        retries=3,
    )
    agent.tool(read_alert)
    agent.tool(list_alerts)
    agent.tool(read_metrics)
    agent.tool(read_logs)
    agent.tool(check_link)
    agent.tool(recent_changes)
    agent.tool(list_runbooks)
    agent.tool(read_runbook)
    agent.tool(restart_instance)
    agent.output_validator(check_recovery)
    return agent
