"""Build the Grafana "Meridian workbench" dashboard and write it into docker-compose.yml.

The dashboard lives inline in the compose file (configs.grafana-meridian-workbench-dashboard), so
Compose writes it world-readable; edit this script, not the inline JSON, and run it:

    python telemetry/build_dashboard.py

Tempo 3.0 drops spans when `sum_over_time` adds up several spans in one series, so every sum here
queries one span per series (grouped by run id) and lets Grafana add the series up.
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.yml"
INLINE_BLOCK = re.compile(
    r"(  grafana-meridian-workbench-dashboard:\n    content: \|\n)(.*?)(\n  # yamllint enable rule:line-length\n)",
    re.DOTALL,
)

DATASOURCE = {"type": "tempo", "uid": "tempo"}
# :pipe joins the chosen values unescaped; :regex would turn "/" into "\/", which TraceQL rejects.
RUN = (
    'span:name="workbench.run" && span.meridian.harness=~"${harness:pipe}" '
    '&& span.meridian.case_id=~"${case_id:pipe}" && span.meridian.model=~"${model:pipe}"'
)
ROOT = "{" + RUN + "}"
AGENT_USAGE = ROOT + ' >> {span:name="meridian.agent_usage"}'
# Unique per run, unlike the 8-character run id.
RUN_ID = "trace:id"
# Tempo returns label values quoted ("\"name\""); show them bare.
UNQUOTE = [
    {"type": "regex", "options": {"pattern": '^"(.*)"$', "result": {"text": "$1"}}}
]
RUN_COLUMNS = {
    "time": "Started",
    "meridian.case_id": "Case",
    "meridian.harness": "Harness",
    "meridian.model": "Model",
    "meridian.outcome": "Outcome",
    "meridian.cost_usd": "Cost",
    "duration": "Duration",
    "meridian.error": "Error",
    "meridian.run_id": "Run",
    "spanID": "Span",
}
SELECT_RUN = (
    " | select(span.meridian.case_id, span.meridian.harness, span.meridian.model, "
    "span.meridian.outcome, span.meridian.error, span.meridian.cost_usd, span.meridian.run_id)"
)


def grid(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": width, "h": height}


def target(query: str, kind: str | None = "range", **extra: Any) -> dict[str, Any]:
    """A TraceQL query; `kind` is "range" or "instant" for metrics, None for a search."""
    query_target: dict[str, Any] = {
        "refId": "A",
        "datasource": DATASOURCE,
        "queryType": "traceql",
        "query": query,
        **extra,
    }
    if kind is not None:
        query_target["metricsQueryType"] = kind
    return query_target


def child(selector: str) -> str:
    return ROOT + " >> {" + selector + "}"


def summed(selector: str, attribute: str, group: str | None = None) -> str:
    """Sum an attribute with one span per series: by run id, plus the panel's group."""
    labels = ", ".join(label for label in (group, RUN_ID) if label)
    return f"{selector} | sum_over_time(span.{attribute}) by ({labels})"


def grouped_sum(group: str) -> list[dict[str, Any]]:
    """Transformations: labels to columns, one table, then one row per group with its sum."""
    return [
        {"id": "labelsToFields", "options": {"mode": "columns"}},
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {"excludeByName": {"Time": True, RUN_ID: True}}},
        {
            "id": "groupBy",
            "options": {
                "fields": {
                    group: {"operation": "groupby", "aggregations": []},
                    "value": {"operation": "aggregate", "aggregations": ["sum"]},
                }
            },
        },
    ]


def units(unit: str, decimals: int | None) -> dict[str, Any]:
    defaults: dict[str, Any] = {"unit": unit}
    if decimals is not None:
        defaults["decimals"] = decimals
    return defaults


@dataclass
class Dashboard:
    panels: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        kind: str,
        title: str,
        position: dict[str, int],
        targets: list[dict[str, Any]],
        description: str = "",
        **extra: Any,
    ) -> None:
        panel = {
            "id": len(self.panels) + 1,
            "type": kind,
            "title": title,
            "datasource": DATASOURCE,
            "gridPos": position,
            "targets": targets,
            **extra,
        }
        if description:
            panel["description"] = description
        self.panels.append(panel)

    def row(self, title: str, y: int) -> None:
        self.panels.append(
            {
                "id": len(self.panels) + 1,
                "type": "row",
                "title": title,
                "collapsed": False,
                "gridPos": grid(0, y, 24, 1),
                "panels": [],
            }
        )

    def count(
        self, title: str, x: int, y: int, query: str, description: str = ""
    ) -> None:
        """A count over the time range: range query, summed by Grafana (Tempo counts correctly)."""
        self.add(
            "stat",
            title,
            grid(x, y, 4, 4),
            [target(query)],
            description,
            fieldConfig={"defaults": {"unit": "none", **STAT_COLOR}, "overrides": []},
            options=stat_options("sum", ""),
        )

    def total(
        self,
        title: str,
        x: int,
        y: int,
        query: str,
        calc: str,
        unit: str = "none",
        decimals: int | None = None,
        description: str = "",
    ) -> None:
        """A sum or mean over one-span series, combined by Grafana."""
        self.add(
            "stat",
            title,
            grid(x, y, 4, 4),
            [target(query, "instant")],
            description,
            fieldConfig={
                "defaults": {**units(unit, decimals), **STAT_COLOR},
                "overrides": [],
            },
            transformations=[
                {"id": "labelsToFields", "options": {"mode": "columns"}},
                {"id": "merge", "options": {}},
            ],
            options=stat_options(calc, "/^value$/"),
        )

    def series(
        self, title: str, x: int, y: int, query: str, description: str = ""
    ) -> None:
        custom = {
            "drawStyle": "bars",
            "fillOpacity": 60,
            "lineWidth": 1,
            "stacking": {"mode": "normal"},
            "spanNulls": True,
        }
        self.add(
            "timeseries",
            title,
            grid(x, y, 8, 8),
            [target(query)],
            description,
            fieldConfig={
                "defaults": {"unit": "none", "custom": custom},
                "overrides": [],
            },
            options={
                "legend": {
                    "displayMode": "list",
                    "placement": "bottom",
                    "showLegend": True,
                },
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
        )

    def bars(
        self,
        title: str,
        position: dict[str, int],
        query_target: dict[str, Any],
        calc: str,
        defaults: dict[str, Any],
        description: str = "",
        transformations: list[dict[str, Any]] | None = None,
        rows: bool = False,
    ) -> None:
        self.add(
            "bargauge",
            title,
            position,
            [query_target],
            description,
            fieldConfig={
                "defaults": {**defaults, "color": {"mode": "palette-classic"}},
                "overrides": [],
            },
            transformations=transformations or [],
            options={
                "orientation": "horizontal",
                "displayMode": "basic",
                "showUnfilled": True,
                "valueMode": "text",
                "namePlacement": "left",
                "reduceOptions": {
                    "calcs": [] if rows else [calc],
                    "fields": "",
                    "values": rows,
                },
            },
        )

    def summed_bars(
        self,
        title: str,
        x: int,
        y: int,
        width: int,
        selector: str,
        attribute: str,
        group: str,
        unit: str = "currencyUSD",
        decimals: int | None = 4,
        description: str = "",
    ) -> None:
        self.bars(
            title,
            grid(x, y, width, 8),
            target(summed(selector, attribute, group), "instant"),
            "sum",
            {**units(unit, decimals), "mappings": UNQUOTE},
            description,
            grouped_sum(group),
            rows=True,
        )

    def runs_table(self, title: str, y: int, query: str, description: str) -> None:
        organize = {
            "id": "organize",
            "options": {
                "excludeByName": {
                    "traceService": True,
                    "traceName": True,
                    "name": True,
                },
                "renameByName": RUN_COLUMNS,
                "indexByName": {name: index for index, name in enumerate(RUN_COLUMNS)},
            },
        }
        cost = {
            "matcher": {"id": "byName", "options": "Cost"},
            "properties": [
                {"id": "unit", "value": "currencyUSD"},
                {"id": "decimals", "value": 4},
            ],
        }
        self.add(
            "table",
            title,
            grid(0, y, 24, 10),
            [target(query, None, limit=100, spss=1, tableType="spans")],
            description,
            transformations=[organize],
            fieldConfig={"defaults": {}, "overrides": [cost]},
        )


STAT_COLOR = {"color": {"mode": "fixed", "fixedColor": "text"}}


def stat_options(calc: str, fields: str) -> dict[str, Any]:
    return {
        "reduceOptions": {"calcs": [calc], "fields": fields, "values": False},
        "colorMode": "none",
        "graphMode": "none",
        "textMode": "value",
    }


def variable(name: str, label: str, tag: str) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DATASOURCE,
        # Tag values by bare name: Grafana finds the scope (span.) itself.
        "query": {
            "refId": "TempoDatasourceVariableQueryEditor-VariableQuery",
            "type": 1,
            "label": tag,
        },
        "definition": tag,
        "refresh": 2,
        "multi": True,
        "includeAll": True,
        "allValue": ".*",
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        "sort": 1,
    }


def build() -> dict[str, Any]:
    board = Dashboard()

    board.row("Overview", 0)
    board.count("Runs", 0, 1, ROOT + " | count_over_time()")
    board.count(
        "Passed",
        4,
        1,
        "{" + RUN + ' && span.meridian.outcome="passed"} | count_over_time()',
        "Runs whose checks all passed, with no error.",
    )
    board.count(
        "Errored",
        8,
        1,
        "{"
        + RUN
        + ' && (span.meridian.outcome="errored" || status=error)} | count_over_time()',
        "Runs that stopped without a report (usage limit, agent error) or raised.",
    )
    board.total(
        "Cost",
        12,
        1,
        summed(ROOT, "meridian.cost_usd"),
        "sum",
        "currencyUSD",
        4,
        "Priced by PydanticAI through genai-prices. Runs on unpriced models, "
        "such as the offline test model, add nothing.",
    )
    board.total(
        "Cost per run",
        16,
        1,
        summed(ROOT, "meridian.cost_usd"),
        "mean",
        "currencyUSD",
        4,
        "Mean over priced runs.",
    )
    board.total("Model calls", 20, 1, summed(ROOT, "meridian.model_calls"), "sum")

    board.row("Over time", 5)
    board.series(
        "Runs by harness",
        0,
        6,
        ROOT + " | count_over_time() by (span.meridian.harness)",
    )
    board.series(
        "Verdicts",
        8,
        6,
        ROOT + " | count_over_time() by (span.meridian.outcome)",
        "The workbench's outcome: passed, failed, errored or not_evaluated (no check).",
    )
    board.series(
        "Runs by model", 16, 6, ROOT + " | count_over_time() by (span.meridian.model)"
    )

    board.row("Where cost and time go", 14)
    board.summed_bars(
        "Cost by harness", 0, 15, 8, ROOT, "meridian.cost_usd", "span.meridian.harness"
    )
    board.summed_bars(
        "Cost by case", 8, 15, 8, ROOT, "meridian.cost_usd", "span.meridian.case_id"
    )
    board.bars(
        "Run duration p50 / p95 by harness",
        grid(16, 15, 8, 8),
        target(
            ROOT
            + " | quantile_over_time(duration, .5, .95) by (span.meridian.harness)",
            "instant",
        ),
        "lastNotNull",
        units("s", None),
        transformations=[
            {
                "id": "renameByRegex",
                "options": {
                    "regex": '.*p=([0-9.]+).*span.meridian.harness="([^"]+)".*',
                    "renamePattern": "$2 p$1",
                },
            }
        ],
    )

    board.row("Agents and tools", 23)
    board.summed_bars(
        "Cost by agent",
        0,
        24,
        6,
        AGENT_USAGE,
        "meridian.cost_usd",
        "span.meridian.agent",
        description="Agents are named by the harness; unnamed ones show as agent.",
    )
    board.summed_bars(
        "Input tokens by agent",
        6,
        24,
        6,
        AGENT_USAGE,
        "meridian.input_tokens",
        "span.meridian.agent",
        "none",
        None,
    )
    board.bars(
        "Tool calls by tool",
        grid(12, 24, 6, 8),
        target(
            child('span.gen_ai.operation.name="execute_tool"')
            + " | count_over_time() by (span.gen_ai.tool.name)"
        ),
        "sum",
        units("none", None),
    )
    board.bars(
        "Tool errors by tool",
        grid(18, 24, 6, 8),
        target(
            child('span.gen_ai.operation.name="execute_tool" && status=error')
            + " | count_over_time() by (span.gen_ai.tool.name)"
        ),
        "sum",
        units("none", None),
        "Tool calls that raised, including refused actions.",
    )

    board.row("Runs", 32)
    board.runs_table(
        "Recent runs",
        33,
        ROOT + SELECT_RUN,
        "Open a trace ID to see the run's agents, model calls and tool calls.",
    )
    board.runs_table(
        "Failed runs",
        43,
        "{"
        + RUN
        + ' && (span.meridian.outcome!="passed" || status=error)}'
        + SELECT_RUN,
        "Every run whose outcome is not passed.",
    )

    dashboard = {
        "uid": "meridian-workbench",
        "title": "Meridian workbench",
        "description": "Course 2 incident-agent runs traced by the workbench: "
        "outcomes, cost, time, agents and tools.",
        "tags": ["meridian", "workbench"],
        "editable": False,
        "schemaVersion": 41,
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "",
        "templating": {
            "list": [
                variable("harness", "Harness", "meridian.harness"),
                variable("case_id", "Case", "meridian.case_id"),
                variable("model", "Model", "meridian.model"),
            ]
        },
        "panels": board.panels,
    }
    return dashboard


def write_inline(dashboard: dict[str, Any], compose_file: Path) -> None:
    """Replace the inline dashboard in the compose file; $$ is a literal $ for Compose."""
    text = json.dumps(dashboard, indent=2).replace("$", "$$")
    compose = compose_file.read_text(encoding="utf-8")
    if len(INLINE_BLOCK.findall(compose)) != 1:
        raise SystemExit(f"{compose_file}: expected one inline dashboard block")
    updated = INLINE_BLOCK.sub(
        lambda match: match.group(1) + textwrap.indent(text, "      ") + match.group(3),
        compose,
    )
    compose_file.write_text(updated, encoding="utf-8")


def main() -> None:
    write_inline(build(), COMPOSE_FILE)


if __name__ == "__main__":
    main()
