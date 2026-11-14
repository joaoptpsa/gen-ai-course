"""Pieces shared by the workbench pages. Pages hold no logic: every action calls `app.commands`."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar

import streamlit as st
from pydantic_ai.models.test import TestModel

from app import commands

T = TypeVar("T")

OFFLINE_MODEL = "offline test model (no API calls)"
APPROVERS = {
    "Scenario's own approver": None,
    "Approve everything": "approve_all",
    "Deny everything": "deny_all",
}
HANDLED_ERRORS = (LookupError, ValueError, FileExistsError, RuntimeError, SystemExit)
JOB_POLL_SECONDS = 0.2
# Streamlit forgets a widget's value once its page is left. These keys are kept: the model choice,
# so a run does not fall back to the paid default, and the YAML tab's text, so a loaded case is
# not swapped for the form's rebuild.
KEPT_WIDGET_KEYS = (
    "run-model",
    "run-model-text",
    "cmp-model",
    "cmp-model-text",
    "yaml-scenario",
    "yaml-check",
)


def page(title: str, caption: str) -> None:
    """Start a page: its title and caption, and the widget values kept across pages."""
    st.set_page_config(page_title=f"{title} · Workbench", layout="wide")
    keep_widget_values()
    st.title(title)
    st.caption(caption)


def keep_widget_values() -> None:
    """Re-assign the kept keys, which makes Streamlit hold them while their widget is off the page.

    Every page must do this on every run: a value is dropped at the end of the first run that
    neither renders its widget nor assigns it.
    """
    for key in KEPT_WIDGET_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def call(handler: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Run a command handler; show its error on the page instead of a traceback."""
    try:
        return handler(*args, **kwargs)
    except HANDLED_ERRORS as error:
        show_error(error)
        return None


def show_error(error: BaseException) -> None:
    st.error(f"{type(error).__name__}: {error}")


@dataclass
class JobProgress:
    done: int = 0
    total: int = 0

    def update(self, done: int, total: int, _record: dict[str, Any]) -> None:
        self.done = done
        self.total = total


@dataclass
class Job:
    """A command handler running on its own thread, so a page rerun cannot discard its result."""

    future: Future[Any]
    progress: JobProgress


def start_job(
    key: str,
    handler: Callable[..., Any],
    *args: Any,
    progress_argument: str | None = None,
    **kwargs: Any,
) -> None:
    """Run `handler` in the background under `key`; a job already pending there is left to finish.

    `progress_argument` names the handler's progress callback parameter, when it has one.
    """
    if key in st.session_state:
        return
    progress = JobProgress()
    if progress_argument:
        kwargs[progress_argument] = progress.update
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workbench-job")
    future = executor.submit(handler, *args, **kwargs)
    # The thread ends with the job: nothing else is submitted.
    executor.shutdown(wait=False)
    st.session_state[key] = Job(future, progress)


def await_job(key: str, result_key: str, waiting_text: str) -> None:
    """Wait for the job under `key`, if there is one, and keep its result under `result_key`.

    A rerun only interrupts the waiting: the job runs on and the next render waits for it again.
    """
    job: Job | None = st.session_state.get(key)
    if job is None:
        return
    with st.spinner(waiting_text):
        bar = st.empty()
        while not job.future.done():
            if job.progress.total:
                fraction = job.progress.done / job.progress.total
                bar.progress(
                    fraction, text=f"{job.progress.done}/{job.progress.total} finished"
                )
            time.sleep(JOB_POLL_SECONDS)
        _keep_outcome(key, result_key, job)


def _keep_outcome(key: str, result_key: str, job: Job) -> None:
    """Move a finished job's result to `result_key`, or show its error, then forget the job.

    A pending rerun takes effect at the next Streamlit call, so the result is stored before any,
    and a failed job is forgotten only once its error is on the page.
    """
    failure = job.future.exception()
    if failure is None:
        st.session_state[result_key] = job.future.result()
        del st.session_state[key]
        return
    if not isinstance(failure, HANDLED_ERRORS):
        del st.session_state[key]
        raise failure
    show_error(failure)
    del st.session_state[key]


def cli_hint(command: str) -> None:
    """Show the CLI command that does the same as the action on the page."""
    st.code(f"bin/mrx-project {command}", language="bash")


def model_picker(key: str) -> Any:
    """A model for runs: the .env default, any PydanticAI model string, or an offline test model."""
    default = commands.default_model_name()
    choice = st.selectbox(
        "Model", [default, OFFLINE_MODEL, "other…"], key=f"{key}-model"
    )
    if choice == OFFLINE_MODEL:
        return TestModel()
    if choice == "other…":
        # The default goes in through session state: a kept key must not also get `value=`.
        st.session_state.setdefault(f"{key}-model-text", default)
        return st.text_input("Model string", key=f"{key}-model-text")
    return choice


def model_flag(model: Any) -> str:
    if isinstance(model, TestModel):
        return "--offline"
    return f"--model {model}"


def approver_picker(key: str) -> str | None:
    """None keeps the scenario's approver; otherwise an approver string the CLI accepts."""
    label = st.selectbox(
        "Approver", [*APPROVERS, "Approve only these roles…"], key=f"{key}-approver"
    )
    if label in APPROVERS:
        return APPROVERS[label]
    roles = st.text_input(
        "Roles (comma separated)", value="on-call,incident-manager", key=f"{key}-roles"
    )
    return f"roles:{roles}"


def cases() -> list[dict[str, Any]]:
    return commands.cases_list()


def harnesses() -> list[dict[str, Any]]:
    return commands.harnesses_list()
