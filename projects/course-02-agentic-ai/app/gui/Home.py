"""Workbench entry page: what it is, where to go, and how far the project is."""

from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

from app import commands
from app.gui import common

PAGES = [
    (
        "pages/1_Scenario_explorer.py",
        "Scenario explorer",
        "Replay a case tick by tick, no agent.",
    ),
    (
        "pages/2_Run_an_agent.py",
        "Run an agent",
        "Run one harness on one case and read the trace.",
    ),
    (
        "pages/3_Compare_versions.py",
        "Compare versions",
        "Run harnesses over cases and diff saved sets.",
    ),
    ("pages/4_Requirements.py", "Requirements", "Track evidence for each requirement."),
    ("pages/5_Case_authoring.py", "Case authoring", "Write and validate new cases."),
]


def show_intro() -> None:
    st.markdown(
        "The workbench is where the project's agent harnesses are built and judged. "
        "Explore the simulated incident cases, run a harness on a case, compare versions "
        "over the same cases, and track the requirements with the evidence collected. "
        "Every action here is also a CLI command."
    )


def show_links() -> None:
    columns = st.columns(len(PAGES))
    for column, (path, label, help_text) in zip(columns, PAGES, strict=True):
        with column:
            st.page_link(path, label=label)
            st.caption(help_text)


def show_counts() -> None:
    columns = st.columns(3)
    columns[0].metric("Cases", len(common.cases()))
    columns[1].metric("Harnesses", len(common.harnesses()))
    columns[2].metric("Saved result sets", len(commands.results_list()))


def show_countdown(status: dict[str, Any]) -> None:
    seconds_left = int(status["seconds_left"])
    days, remainder = divmod(abs(seconds_left), 86400)
    hours = remainder // 3600
    sign = "-" if seconds_left < 0 else ""
    st.subheader("Requirements countdown")
    columns = st.columns(2)
    columns[0].metric("Deadline", status["deadline"][:10])
    columns[1].metric("Time left", f"{sign}{days} days {hours} hours")
    per_status = Counter(item["status"] for item in status["items"])
    st.table({"status": list(per_status), "requirements": list(per_status.values())})


def main() -> None:
    common.page(
        "Project workbench", "Cases, harnesses, results and requirements in one place."
    )
    show_intro()
    show_links()
    show_counts()
    status = common.call(commands.requirements_status)
    if status is not None:
        show_countdown(status)
    common.cli_hint("--help")


main()
