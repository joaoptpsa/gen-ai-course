"""Replay a case's simulation tick by tick, without any agent."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app import commands
from app.gui import common

METRICS = ["latency_ms", "error_rate", "queue_depth"]
LINK_COLOURS = {"up": "#2e7d32", "degraded": "#f9a825", "down": "#c62828"}
HEALTH_COLOURS = {"healthy": "#c8e6c9", "degraded": "#fff59d", "failing": "#ef9a9a"}
LEVELS = ["ERROR", "WARN", "INFO", "DEBUG"]
ERROR_RATE_FAILING = 0.2
ERROR_RATE_DEGRADED = 0.02
LATENCY_FAILING_MS = 1000.0
LATENCY_DEGRADED_MS = 300.0


@st.cache_data(show_spinner="Simulating…")
def explore_cached(case_id: str, ticks: int, modified: float) -> dict[str, Any]:
    """`modified` is only part of the cache key: an edited case file is simulated again."""
    return commands.explore(case_id, ticks)


def health(component: dict[str, Any]) -> str:
    if (
        component["error_rate"] >= ERROR_RATE_FAILING
        or component["latency_ms"] >= LATENCY_FAILING_MS
    ):
        return "failing"
    if (
        component["error_rate"] >= ERROR_RATE_DEGRADED
        or component["latency_ms"] >= LATENCY_DEGRADED_MS
    ):
        return "degraded"
    return "healthy"


def topology_dot(topology: list[dict[str, Any]], frame: dict[str, Any]) -> str:
    lines = ["digraph {", "rankdir=LR;", 'node [shape=box, style="filled,rounded"];']
    for node in topology:
        name = node["name"]
        component = frame["components"][name]
        colour = HEALTH_COLOURS[health(component)]
        pen = 4 if node["critical"] else 1
        label = f"{name}\\n{component['latency_ms']:.0f} ms, err {component['error_rate']:.1%}"
        lines.append(
            f'"{name}" [label="{label}", fillcolor="{colour}", penwidth={pen}];'
        )
    for link in frame["links"]:
        colour = LINK_COLOURS[link["state"]]
        lines.append(
            f'"{link["source"]}" -> "{link["target"]}" [color="{colour}", penwidth=2];'
        )
    lines.append("}")
    return "\n".join(lines)


def metric_frame(frames: list[dict[str, Any]], metric: str) -> pd.DataFrame:
    rows = {
        frame["tick"]: {name: c[metric] for name, c in frame["components"].items()}
        for frame in frames
    }
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def show_brief(brief: dict[str, Any]) -> None:
    st.subheader("Brief the agent receives")
    st.json(brief)


def show_topology(result: dict[str, Any], frame: dict[str, Any]) -> None:
    st.subheader(f"Topology at tick {frame['tick']} ({frame['time']})")
    st.caption("Thick border: critical component. Fill: health. Edge: link state.")
    st.graphviz_chart(topology_dot(result["topology"], frame))


def show_metric_charts(frames: list[dict[str, Any]]) -> None:
    st.subheader("Metrics per component")
    for metric in METRICS:
        st.caption(metric)
        st.line_chart(metric_frame(frames, metric))


def show_table(title: str, rows: list[dict[str, Any]]) -> None:
    st.markdown(f"**{title}**")
    if not rows:
        st.caption("none")
        return
    st.dataframe(pd.DataFrame(rows).astype(str), width="stretch", hide_index=True)


def show_logs(frame: dict[str, Any], warmup_logs: list[dict[str, Any]]) -> None:
    st.subheader("Logs")
    with st.expander(f"Warm-up logs ({len(warmup_logs)})"):
        show_table("Warm-up log lines", warmup_logs)
    logs = frame["logs"]
    components = sorted({log["component"] for log in logs})
    levels = sorted(
        {log["level"] for log in logs},
        key=lambda level: LEVELS.index(level) if level in LEVELS else 99,
    )
    left, right = st.columns(2)
    chosen_components = left.multiselect("Components", components, default=components)
    chosen_levels = right.multiselect("Levels", levels, default=levels)
    shown = [
        log
        for log in logs
        if log["component"] in chosen_components and log["level"] in chosen_levels
    ]
    show_table(f"Log lines ({len(shown)} of {len(logs)})", shown)


def show_state(frame: dict[str, Any]) -> None:
    st.subheader("State at this tick")
    show_table("Alerts open", frame["alerts_open"])
    show_table("Alerts opened this tick", frame["alerts_opened"])
    show_table("New tickets", frame["tickets_new"])
    show_table("Events", frame["events"])
    show_table("Active faults", frame["active_faults"])
    show_table("Active changes", frame["active_changes"])


def main() -> None:
    common.page(
        "Scenario explorer", "Replay a case's simulation, tick by tick. No agent runs."
    )
    case_list = common.cases()
    if not case_list:
        st.warning("No cases found.")
        return
    by_id = {case["case_id"]: case for case in case_list}
    left, right = st.columns([3, 1])
    case_id = left.selectbox(
        "Case", list(by_id), format_func=lambda cid: f"{cid}: {by_id[cid]['title']}"
    )
    ticks = int(
        right.number_input("Ticks", min_value=1, max_value=240, value=30, step=1)
    )
    st.info(by_id[case_id]["incident_summary"])

    result = common.call(explore_cached, case_id, ticks, by_id[case_id]["modified"])
    if result is None:
        return
    frames = result["frames"]
    show_brief(result["brief"])
    tick_values = [frame["tick"] for frame in frames]
    if len(tick_values) > 1:
        tick = st.select_slider("Tick", options=tick_values, value=tick_values[-1])
    else:
        tick = tick_values[0]
    frame = frames[tick_values.index(tick)]
    show_topology(result, frame)
    show_metric_charts(frames)
    show_logs(frame, result["warmup_logs"])
    show_state(frame)
    common.cli_hint(f"explore {case_id} --ticks {ticks}")


main()
