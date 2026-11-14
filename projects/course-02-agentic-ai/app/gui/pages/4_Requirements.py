"""Project requirements: status from run results, evidence cases and notes."""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

from app import commands
from app.gui import common

GROUP_ORDER = ["capability", "execution", "criterion", "deliverable"]
STATUS_BADGES: dict[str, tuple[str, Literal["green", "red", "orange", "gray"]]] = {
    "passing": ("passing", "green"),
    "failing": ("failing", "red"),
    "untested": ("untested", "orange"),
    "no_evidence": ("no evidence", "gray"),
}


def format_countdown(seconds_left: float) -> str:
    total = int(abs(seconds_left))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    text = f"{days}d {hours}h {minutes}m"
    return text if seconds_left >= 0 else f"{text} past"


def render_countdown(report: dict[str, Any]) -> None:
    left, right = st.columns(2)
    left.metric("Deadline", report["deadline"])
    right.metric("Time left", format_countdown(report["seconds_left"]))


def render_summary(items: list[dict[str, Any]]) -> None:
    columns = st.columns(len(STATUS_BADGES))
    for column, (status, (label, _)) in zip(
        columns, STATUS_BADGES.items(), strict=True
    ):
        column.metric(label, sum(1 for item in items if item["status"] == status))


def render_evidence_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        st.caption("No evidence cases yet.")
        return
    rows = [
        {
            "case": row["case_id"],
            "runs": row["runs"],
            "passed": row["passed"],
            "pass rate": row["pass_rate"],
        }
        for row in cases
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


def render_note_editor(requirement: dict[str, Any]) -> None:
    item_id = requirement["id"]
    text = st.text_area(
        "Notes", value=requirement["notes"] or "", key=f"note-{item_id}"
    )
    common.cli_hint(f"requirements note {item_id} {text!r}")
    clicked = st.button("Save note", key=f"save-note-{item_id}")
    if clicked and common.call(commands.requirements_note, item_id, text) is not None:
        st.rerun()


def evidence_action(
    handler: Any, label: str, item_id: str, case_id: str | None, verb: str
) -> None:
    if case_id:
        common.cli_hint(f"requirements evidence {verb} {item_id} {case_id}")
    clicked = st.button(label, key=f"{verb}-button-{item_id}", disabled=not case_id)
    if clicked and common.call(handler, item_id, case_id) is not None:
        st.rerun()


def render_evidence_editor(requirement: dict[str, Any]) -> None:
    item_id = requirement["id"]
    case_ids = [row["case_id"] for row in common.cases()]
    addable = [
        case_id for case_id in case_ids if case_id not in requirement["evidence"]
    ]
    add_column, remove_column = st.columns(2)
    with add_column:
        added = st.selectbox("Add evidence case", addable, key=f"add-{item_id}")
        evidence_action(
            commands.requirements_evidence_add, "Add evidence", item_id, added, "add"
        )
    with remove_column:
        removed = st.selectbox(
            "Remove evidence case", requirement["evidence"], key=f"remove-{item_id}"
        )
        evidence_action(
            commands.requirements_evidence_remove,
            "Remove evidence",
            item_id,
            removed,
            "remove",
        )


def render_item(item: dict[str, Any]) -> None:
    requirement = item["requirement"]
    label, colour = STATUS_BADGES[item["status"]]
    title = f"{requirement['id']}  {requirement['title']}"
    with st.expander(title):
        st.badge(label, color=colour)
        st.write(requirement["description"])
        render_evidence_cases(item["cases"])
        render_note_editor(requirement)
        render_evidence_editor(requirement)


def render_group(group: str, items: list[dict[str, Any]]) -> None:
    members = [item for item in items if item["requirement"]["group"] == group]
    if not members:
        return
    st.subheader(group.capitalize())
    for item in members:
        render_item(item)


def result_set_choice() -> str | None:
    saved = common.call(commands.results_list) or []
    options = {f"{row['set_id']}  {row['label'] or ''}": row["set_id"] for row in saved}
    label = st.selectbox(
        "Status computed from", ["Newest runs per case", *options], key="req-set"
    )
    return options.get(label)


common.page(
    "Requirements",
    "Where each project requirement stands, from the evidence cases' runs.",
)
set_id = result_set_choice()
common.cli_hint("requirements status" + (f" --set {set_id}" if set_id else ""))
report = common.call(commands.requirements_status, set_id=set_id)
if report is not None:
    render_countdown(report)
    render_summary(report["items"])
    for group in GROUP_ORDER:
        render_group(group, report["items"])
