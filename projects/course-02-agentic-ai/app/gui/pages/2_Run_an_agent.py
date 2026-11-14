"""Run one harness on one case and read the outcome."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from app import commands
from app.gui import common

RESULT_KEY = "run-result"
RUN_JOB = "run-job"


def show_cost_warning() -> None:
    st.warning(
        "Real models cost money. Choose the offline test model to run with no API calls."
    )


def show_banner(record: dict[str, Any]) -> None:
    passed = record["passed"]
    if passed is None:
        st.info("Not evaluated: this case has no checks.")
        return
    if passed:
        st.success("Passed")
        return
    st.error("Failed")


def show_checks(checks: list[dict[str, Any]]) -> None:
    for check in checks:
        mark = "✓" if check["passed"] else "✗"
        st.markdown(f"{mark} **{check['name']}**: {check['detail']}")


def show_metrics(record: dict[str, Any]) -> None:
    columns = st.columns(4)
    columns[0].metric("Input tokens", record["input_tokens"])
    columns[1].metric("Requests", record["requests"])
    columns[2].metric("End tick", record["end_tick"])
    columns[3].metric("Duration (s)", f"{record['duration_s']:.2f}")


def show_trace(trace: list[dict[str, Any]]) -> None:
    st.subheader("Trace")
    if not trace:
        st.caption("No tool calls.")
        return
    summary = [
        {
            "step": step["step"],
            "tick": step["tick"],
            "time": step["time"],
            "tool": step["tool"],
            "error": step["error"],
        }
        for step in trace
    ]
    st.dataframe(pd.DataFrame(summary).astype(str), width="stretch", hide_index=True)
    for step in trace:
        with st.expander(f"{step['step']}. {step['tool']}"):
            st.markdown("Args")
            st.json(step["args"])
            st.markdown("Result")
            st.json(step["result"])


def show_approvals(approvals: list[Any]) -> None:
    st.subheader("Approvals")
    if not approvals:
        st.caption("none")
        return
    rows = [a if isinstance(a, dict) else {"approval": a} for a in approvals]
    st.dataframe(pd.DataFrame(rows).astype(str), width="stretch", hide_index=True)


def show_messages(messages: list[dict[str, Any]]) -> None:
    with st.expander(f"Model messages ({len(messages)})"):
        for message in messages:
            st.markdown(f"**{message['kind']}**")
            st.text(message["text"])


def show_result(result: dict[str, Any]) -> None:
    record = result["record"]
    st.divider()
    st.caption(f"{record['harness']} on {record['case_id']} with {record['model']}")
    show_banner(record)
    show_checks(record["checks"])
    show_metrics(record)
    if record["error"]:
        st.error(record["error"])
    st.subheader("Report")
    st.json(record["report"] if record["report"] is not None else json.dumps(None))
    show_trace(record["trace"])
    show_approvals(record["approvals"])
    show_messages(record["messages"])
    if result["result_set"]:
        st.success(f"Saved as result set {result['result_set']}")


def cli_command(
    harness: str,
    case_id: str,
    model: Any,
    approver: str | None,
    max_requests: int,
    label: str,
) -> str:
    parts = ["run", harness, case_id, common.model_flag(model)]
    if approver:
        parts += ["--approver", approver]
    parts += ["--max-requests", str(max_requests)]
    if label:
        parts += ["--save", label]
    return " ".join(parts)


def main() -> None:
    common.page(
        "Run an agent", "Run one harness on one case and inspect the checks and trace."
    )
    harness_names = [harness["name"] for harness in common.harnesses()]
    case_ids = [case["case_id"] for case in common.cases()]
    if not harness_names or not case_ids:
        st.warning("No harnesses or cases found.")
        return
    left, right = st.columns(2)
    harness = left.selectbox("Harness", harness_names)
    case_id = right.selectbox("Case", case_ids)
    if harness is None or case_id is None:
        return
    left, right = st.columns(2)
    with left:
        model = common.model_picker("run")
    with right:
        approver = common.approver_picker("run")
    max_requests = int(
        st.number_input("Max requests", min_value=1, max_value=200, value=20)
    )
    label = st.text_input("Save as result set (optional label)").strip()
    show_cost_warning()
    common.cli_hint(cli_command(harness, case_id, model, approver, max_requests, label))

    if st.button("Run", type="primary"):
        common.start_job(
            RUN_JOB,
            commands.run,
            harness,
            case_id,
            model=model,
            approver=approver,
            max_requests=max_requests,
            save_label=label or None,
        )
    common.await_job(RUN_JOB, RESULT_KEY, "Running…")
    if RESULT_KEY in st.session_state:
        show_result(st.session_state[RESULT_KEY])


main()
