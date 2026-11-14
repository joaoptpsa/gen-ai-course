"""Compare harness versions on the same cases, and review or diff saved result sets."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app import commands
from app.gui import common

SESSIONS = ["s01", "s02", "s03", "s04"]
DIFF_COLOURS = {
    "regression": "background-color: #f8c9c9",
    "improvement": "background-color: #c9f0d2",
    "new": "background-color: #dbe7fb",
    "missing": "background-color: #fbe9c3",
}
BY_OPTIONS = ["harness_case", "case"]
COMPARE_JOB = "cmp-job"
RESULT_KEY = "last-comparison"


def rate_colour(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if value >= 1.0:
        return "background-color: #c9f0d2"
    if value <= 0.0:
        return "background-color: #f8c9c9"
    return "background-color: #fbe9c3"


def status_colour(status: str) -> str:
    return DIFF_COLOURS.get(status, "")


def summary_frame(summary: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(summary)


def render_matrix(summary: list[dict[str, Any]]) -> None:
    frame = summary_frame(summary)
    if frame.empty:
        st.info("No runs to summarise.")
        return
    matrix = frame.pivot(index="case_id", columns="harness", values="pass_rate")
    st.markdown("**Pass rate (cases x harnesses)**")
    st.dataframe(
        matrix.style.map(rate_colour).format("{:.0%}", na_rep="n/a"),
        width="stretch",
    )


def render_details(summary: list[dict[str, Any]]) -> None:
    frame = summary_frame(summary)
    if frame.empty:
        return
    st.markdown("**Runs, tokens and errors**")
    columns = ["harness", "case_id", "runs", "passed", "errors", "mean_input_tokens"]
    st.dataframe(frame[columns], width="stretch", hide_index=True)
    failing = [
        {
            "harness": row["harness"],
            "case_id": row["case_id"],
            "check": name,
            "count": count,
        }
        for row in summary
        for name, count in row["failing_checks"].items()
    ]
    if not failing:
        st.success("No failing checks.")
        return
    st.markdown("**Failing checks**")
    st.dataframe(pd.DataFrame(failing), width="stretch", hide_index=True)


def render_diff(diff: list[dict[str, Any]] | None) -> None:
    if diff is None:
        return
    st.markdown("**Diff against the baseline**")
    if not diff:
        st.info("Nothing to compare.")
        return
    frame = pd.DataFrame(diff)
    regressions = sum(1 for row in diff if row["status"] == "regression")
    if regressions:
        st.error(f"{regressions} regression(s)")
    styled = frame.style.map(status_colour, subset=["status"])
    st.dataframe(styled, width="stretch", hide_index=True)


def render_comparison(comparison: dict[str, Any]) -> None:
    if comparison["result_set"]:
        st.success(f"Saved as result set `{comparison['result_set']}`")
    render_matrix(comparison["summary"])
    render_details(comparison["summary"])
    render_diff(comparison["diff"])


def session_filter(case_ids: list[str]) -> list[str]:
    prefixes = st.multiselect("Quick filter by session", SESSIONS, key="cmp-sessions")
    if not prefixes:
        return case_ids
    return [case_id for case_id in case_ids if case_id.split("-")[0] in prefixes]


def baseline_options() -> dict[str, str]:
    saved = common.call(commands.results_list) or []
    return {f"{row['set_id']}  {row['label'] or ''}": row["set_id"] for row in saved}


def render_form() -> dict[str, Any]:
    harness_names = [row["name"] for row in common.harnesses()]
    all_case_ids = [row["case_id"] for row in common.cases()]
    harness_choice = st.multiselect("Harnesses", harness_names, key="cmp-harnesses")
    case_pool = session_filter(all_case_ids)
    case_choice = st.multiselect(
        "Cases", all_case_ids, default=case_pool, key=f"cmp-cases-{'-'.join(case_pool)}"
    )
    left, right = st.columns(2)
    with left:
        reps = int(st.number_input("Repetitions", min_value=1, value=1, key="cmp-reps"))
        max_requests = int(
            st.number_input(
                "Max requests per run", min_value=1, value=20, key="cmp-max-requests"
            )
        )
        workers = int(
            st.number_input("Parallel workers", min_value=1, value=4, key="cmp-workers")
        )
    with right:
        model = common.model_picker("cmp")
        approver = common.approver_picker("cmp")
    options = baseline_options()
    baseline_label = st.selectbox(
        "Baseline (optional)", ["none", *options], key="cmp-baseline"
    )
    by = st.selectbox("Diff by", BY_OPTIONS, key="cmp-by")
    label = st.text_input("Save label (optional)", key="cmp-label")
    return {
        "harnesses": harness_choice,
        "case_ids": case_choice,
        "reps": reps,
        "model": model,
        "approver": approver,
        "max_requests": max_requests,
        "max_workers": workers,
        "baseline": options.get(baseline_label),
        "by": by,
        "save_label": label.strip() or None,
    }


def cli_command(form: dict[str, Any]) -> str:
    parts = ["compare"]
    parts += [f"--harness {name}" for name in form["harnesses"]]
    parts += [f"--case {case_id}" for case_id in form["case_ids"]]
    parts += [f"--reps {form['reps']}", common.model_flag(form["model"])]
    if form["approver"]:
        parts.append(f"--approver {form['approver']}")
    parts += [
        f"--max-requests {form['max_requests']}",
        f"--workers {form['max_workers']}",
    ]
    if form["baseline"]:
        parts += [f"--baseline {form['baseline']}", f"--by {form['by']}"]
    if form["save_label"]:
        parts.append(f"--save {form['save_label']!r}")
    return " ".join(parts)


def start_comparison(form: dict[str, Any]) -> None:
    arguments = {key: value for key, value in form.items() if key != "harnesses"}
    common.start_job(
        COMPARE_JOB,
        commands.compare,
        form["harnesses"],
        progress_argument="on_progress",
        **arguments,
    )


def render_compare_section() -> None:
    st.header("Compare versions")
    form = render_form()
    runs = len(form["harnesses"]) * len(form["case_ids"]) * form["reps"]
    uses_real_model = common.model_flag(form["model"]) != "--offline"
    if uses_real_model:
        st.warning(
            f"Real models cost money: this starts {runs} runs (repetitions x harnesses x cases)."
        )
    else:
        st.caption(f"This starts {runs} offline runs.")
    common.cli_hint(cli_command(form))
    can_run = bool(form["harnesses"]) and bool(form["case_ids"])
    if st.button("Run comparison", type="primary", disabled=not can_run):
        start_comparison(form)
    common.await_job(COMPARE_JOB, RESULT_KEY, "Running the comparison…")
    last = st.session_state.get(RESULT_KEY)
    if last:
        render_comparison(last)


def render_saved_list(saved: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(saved)
    st.dataframe(frame, width="stretch", hide_index=True)
    common.cli_hint("results list")


def render_saved_show(set_ids: list[str]) -> None:
    st.subheader("Show a set")
    chosen = st.selectbox("Result set", set_ids, key="saved-show")
    common.cli_hint(f"results show {chosen}")
    shown = common.call(commands.results_show, chosen)
    if shown is None:
        return
    st.caption(
        f"{shown['label'] or 'unlabelled'} · {shown['created_at']} · {len(shown['runs'])} runs"
    )
    render_matrix(shown["summary"])
    render_details(shown["summary"])


def render_saved_diff(set_ids: list[str]) -> None:
    st.subheader("Diff two sets")
    if len(set_ids) < 2:
        st.info("Save at least two result sets to diff them.")
        return
    baseline = st.selectbox("Baseline", set_ids, index=1, key="saved-baseline")
    current = st.selectbox("Current", set_ids, index=0, key="saved-current")
    by = st.selectbox("By", BY_OPTIONS, key="saved-by")
    common.cli_hint(f"results diff {baseline} {current} --by {by}")
    diff = common.call(commands.results_diff, baseline, current, by=by)
    render_diff(diff)


def render_saved_section() -> None:
    st.header("Saved result sets")
    saved = common.call(commands.results_list)
    if not saved:
        st.info("No saved result sets yet. Give a comparison a save label to keep it.")
        return
    render_saved_list(saved)
    set_ids = [row["set_id"] for row in saved]
    render_saved_show(set_ids)
    render_saved_diff(set_ids)


common.page(
    "Compare versions", "Run harness versions on the same cases and see what changed."
)
render_compare_section()
st.divider()
render_saved_section()
