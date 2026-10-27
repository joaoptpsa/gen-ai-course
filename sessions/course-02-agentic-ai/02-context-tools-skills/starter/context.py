"""Exercise 1 — Find the needle without reading the haystack.

The problem
    The gateway is slow and the pager shows 200 alerts. The agent receives
    every alert, about 5 000 log lines and every runbook in its first message:
    more than 100 000 tokens. The cause is often a single line in there, and
    the agent misses it. Sometimes it follows the runbook of an older gateway
    version and restarts the whole service.

    A person on call does not read 5 000 lines. They look for what is unusual,
    open the runbook of the version they run, and fetch the rest when needed.

Build, in this file
    A. build_prompt: what goes in the first message; the rest is fetched with tools.
    B. summarize_logs(component): thousands of log lines -> a short list, unusual lines first.
    C. find_runbook(component): only the runbook that applies to the version in production.
    Then add B and C to TOOLS, and remove read_logs (it returns every line).

Watch out
    - Whatever you take out of the prompt must be reachable with a tool.
    - The cause is not always on the component of the alert: in two cases it is
      in another component's logs, or in a change made to another component.
    - Thousands of identical errors are a symptom. The line that explains them
      can appear once.
    - The model only knows a tool from its name, arguments and docstring.
    - Budget: all the model requests of a run together stay under 40 000 input tokens.

Logs are written from a few dozen templates; only the values change:

    INFO  order accepted id=O481920 member=NORDBANK side=buy
    INFO  order accepted id=O519034 member=ATLAS-SEC side=sell
    WARN  max_connections changed from 500 to 60 (CHG-4471); new connections above the limit are rejected

The first two lines are the same template. The third appears once: it is the cause.

Hints (read only if stuck)
    1. Write the policy in three lines first: always in the prompt; loaded on
       demand; never loaded. Then tell the agent, in INSTRUCTIONS, in which order to look.
    2. Templates: replace with regular expressions, in this order: ids like
       CHG-4471, IP addresses, key=value values, any remaining number. If you
       get dozens of nearly identical templates, you are not replacing enough.
    3. Rare: seen once or twice, or first seen in the last 30 minutes. Return
       each rare template with one full example line and its log ref.
    4. Runbooks: applies_to looks like "order-gateway 2.4.x"; turn x into * and use fnmatch.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from pydantic_ai import RunContext

from meridian.agent_runtime import IncidentDeps

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Investigate the incident, follow the runbook that applies to the version in production, and act when needed.
Look in this order:
1. read_metrics of the alerting component, per instance, to see which instance and what is abnormal.
2. find_runbook for that component and follow it.
3. summarize_logs of the alerting component: a line seen once can explain thousands of errors.
4. If the metrics and those logs already explain the incident, act. If they point elsewhere, or explain
   nothing, summarize_logs of the components it depends on and read recent_changes without a component:
   the cause is not always in the component that alerts, and a change to another component can be it.
When the cause is a change, roll back that change. After an action, call wait_for_recovery for the
affected component with the runbook's recovery criterion, instead of reading metrics again and again.
Take no further action just to speed recovery up. Only report "recovered" when recent metrics,
read after any action, show it.
Cite the evidence you used (metric source_ref values, log refs or change ids).
"""


def build_prompt(brief: dict[str, Any], deps: IncidentDeps) -> str:
    """A. The first message: the incident line and a pointer to the tools.

    Always in the prompt: the incident line. On demand, by tool: metrics, alerts and log summaries,
    runbooks, changes. Never loaded: raw log lines and every runbook.
    """
    return (
        f"Incident {brief['incident_id']} ({brief['time']}): {brief['summary']}\n\n"
        "Open alerts, logs and runbooks are not included here. Fetch what you need with your tools.\n"
    )


def summarize_alerts(deps: IncidentDeps, component: str) -> list[str]:
    """One line per (rule, instance) of a component's open alerts, the rarest first."""
    groups: dict[tuple[str, str | None], list[Any]] = {}
    for alert in deps.sim.alerts.alerts:
        if alert.state == "open" and alert.component == component:
            groups.setdefault((alert.rule, alert.instance), []).append(alert)
    rarest_first = sorted(groups.items(), key=lambda item: len(item[1]))
    lines = [
        f"{rule} {instance or '(all instances)'}: {len(alerts)} open, first {alerts[0].alert_id} at {alerts[0].opened_at}"
        for (rule, instance), alerts in rarest_first
    ]
    return lines


MAX_METRICS_WINDOW_TICKS = 5
READING_FIELDS = ("time", "latency_ms", "error_rate", "queue_depth", "cpu_pct", "memory_pct")


def compact_reading(reading: dict[str, Any]) -> dict[str, Any]:
    """A reading without the constant fields, with each instance on one short line."""
    compact = {field: reading[field] for field in READING_FIELDS}
    if "instances" in reading:
        compact["instances"] = {
            name: f"{state['status']} mem={state['memory_pct']}% cpu={state['cpu_pct']}% lat={state['latency_ms']}ms"
            for name, state in reading["instances"].items()
        }
    return compact


def read_metrics(ctx: RunContext[IncidentDeps], component: str, window_ticks: int = 5, per_instance: bool = False) -> dict[str, Any]:
    """Recent metrics of a component, one reading per minute, the oldest first.

    To follow a recovery, read again with window_ticks=1: the older readings are already known.

    Args:
        component: One of order-gateway, matching-engine, market-data, settlement, reference-db.
        window_ticks: How many of the last minutes to read, 1 to 5. Larger values are capped at 5.
        per_instance: Add the readings of each instance, to see which one is abnormal.
    """
    capped_window = min(window_ticks, MAX_METRICS_WINDOW_TICKS)
    metrics = ctx.deps.tools.read_metrics(component, capped_window, per_instance)
    if "error" in metrics:
        return metrics
    compact = {
        "component": component,
        "version": metrics["readings"][-1]["version"],
        "readings": [compact_reading(reading) for reading in metrics["readings"]],
        "source_ref": metrics["source_ref"],
    }
    return compact


def wait_for_recovery(
    ctx: RunContext[IncidentDeps],
    component: str,
    latency_ms_below: float | None = None,
    error_rate_below: float = 0.01,
    consecutive_readings: int = 3,
    max_minutes: int = 10,
) -> dict[str, Any]:
    """Wait for a component to recover after an action, reading its metrics once a minute inside this call.

    Use it after rolling back or restarting, with the recovery criterion of the runbook, instead of
    calling read_metrics again and again. It returns when the criterion has held for the required
    consecutive readings, or after max_minutes. "recovered" says which: if it is false, the component
    did not recover in that time and the last readings show how it looks.

    Args:
        component: The component to watch, such as order-gateway.
        latency_ms_below: Latency the runbook requires, in ms. Omit it when the runbook sets none.
        error_rate_below: Error rate it must stay under, 0.01 being 1%.
        consecutive_readings: How many readings in a row must meet the criterion.
        max_minutes: How long to wait at most, in minutes.
    """
    streak = 0
    readings: list[dict[str, Any]] = []
    source_ref = None
    for _ in range(max_minutes):
        metrics = ctx.deps.tools.read_metrics(component, 1, False)
        if "error" in metrics:
            return metrics
        reading = compact_reading(metrics["readings"][-1])
        readings.append(reading)
        source_ref = metrics["source_ref"]
        latency_ok = latency_ms_below is None or reading["latency_ms"] < latency_ms_below
        streak = streak + 1 if latency_ok and reading["error_rate"] < error_rate_below else 0
        if streak >= consecutive_readings:
            break
    outcome = {
        "component": component,
        "recovered": streak >= consecutive_readings,
        "minutes_waited": len(readings),
        "readings": readings[-consecutive_readings:],
        "source_ref": source_ref,
    }
    return outcome


def recent_changes(ctx: RunContext[IncidentDeps], component: str | None = None) -> dict[str, Any]:
    """Recent deployments and configuration changes, and whether each one is still active.

    Args:
        component: Only list the changes of this component, such as reference-db. Omit it to list the
            changes of every component: a change to another component can be the cause.
    """
    return ctx.deps.tools.recent_changes(component)


TEMPLATE_SUBSTITUTIONS = (
    (re.compile(r"\b[A-Z]+-\d+\b"), "<id>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"(\w+)=\S+"), r"\1=<value>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<number>"),
)
RARE_MAX_COUNT = 2
RECENT_TICKS = 30
RARE_LIMIT = 20
COMMON_LIMIT = 5


def template_of(message: str) -> str:
    """B. The template of a log line: the line with its variable parts replaced by placeholders."""
    template = message
    for pattern, placeholder in TEMPLATE_SUBSTITUTIONS:
        template = pattern.sub(placeholder, template)
    return template


def group_by_template(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per template: its count, the first line seen, the last time seen and the instances."""
    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        group = groups.setdefault(
            template_of(line["message"]),
            {"count": 0, "first": line, "last_time": line["time"], "instances": set()},
        )
        group["count"] += 1
        group["last_time"] = line["time"]
        group["instances"].add(line["instance"])
    return groups


def is_rare(group: dict[str, Any], latest_tick: int) -> bool:
    """Seen once or twice, or first seen in the last RECENT_TICKS minutes."""
    return group["count"] <= RARE_MAX_COUNT or group["first"]["tick"] >= latest_tick - RECENT_TICKS


def describe_group(template: str, group: dict[str, Any]) -> dict[str, Any]:
    first = group["first"]
    return {
        "template": template,
        "count": group["count"],
        "first_seen": first["time"],
        "last_seen": group["last_time"],
        "instances": sorted(group["instances"]),
        "example": f"{first['message']} [{first['ref']}]",
    }


def summarize_logs(ctx: RunContext[IncidentDeps], component: str) -> dict[str, Any]:
    """Short summary of a component's open alerts and logs: the rare lines first, then the most common ones.

    "open_alerts" groups the component's open alerts by rule and instance, the rarest first: a
    duplicated alert is noise, one on a single instance says where to look. Use this tool instead
    of reading logs or alerts one by one. Lines are grouped by template (values replaced by
    placeholders). "rare" lists templates seen once or twice, or first seen in the last 30 minutes,
    rarest first, each with its count, when and where it appeared, and one full example line with its
    log ref. The line that explains a flood of identical errors often appears once. "common" lists only
    the most frequent templates with their counts. Call it for the alerting component and for its
    dependencies: the cause is not always in the component that alerts.

    Args:
        component: The component whose logs to summarize, such as order-gateway or reference-db.
    """
    lines = ctx.deps.tools.read_logs(component=component, limit=1_000_000)["lines"]
    groups = group_by_template(lines)
    latest_tick = max((line["tick"] for line in lines), default=0)
    rare = [(template, group) for template, group in groups.items() if is_rare(group, latest_tick)]
    common = [(template, group) for template, group in groups.items() if not is_rare(group, latest_tick)]
    rare.sort(key=lambda item: (item[1]["count"], item[1]["first"]["tick"]))
    common.sort(key=lambda item: -item[1]["count"])
    summary = {
        "component": component,
        "total_lines": len(lines),
        "open_alerts": summarize_alerts(ctx.deps, component),
        "distinct_templates": len(groups),
        "rare": [describe_group(template, group) for template, group in rare[:RARE_LIMIT]],
        "rare_omitted": max(0, len(rare) - RARE_LIMIT),
        "common": [{"template": template, "count": group["count"]} for template, group in common[:COMMON_LIMIT]],
    }
    return summary


def find_runbook(ctx: RunContext[IncidentDeps], component: str) -> dict[str, Any]:
    """The runbook that applies to the version of a component running in production.

    Returns the full text of the one runbook whose applies_to matches the component and its
    current version. Older versions of a runbook may recommend actions that are wrong for the
    version in production, so use this instead of guessing a runbook. If none matches, it says so
    and lists what exists.

    Args:
        component: The component to find the runbook for, such as order-gateway.
    """
    version = ctx.deps.tools.read_metrics(component, 1)["readings"][-1]["version"]
    runbooks = ctx.deps.tools.list_runbooks()["runbooks"]
    deployed = f"{component} {version}"
    matches = [runbook for runbook in runbooks if fnmatch.fnmatch(deployed, runbook["applies_to"].replace(".x", ".*"))]
    if not matches:
        return {"error": f"No runbook applies to {deployed}", "available": [runbook["applies_to"] for runbook in runbooks]}
    chosen = max(matches, key=lambda runbook: runbook["version"])
    runbook_text = ctx.deps.tools.read_runbook(chosen["name"], chosen["version"])
    return runbook_text


TOOLS = (read_metrics, summarize_logs, find_runbook, recent_changes, wait_for_recovery)
