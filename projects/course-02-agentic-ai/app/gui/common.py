"""Pieces shared by the workbench pages. Pages hold no logic: every action calls `app.commands`."""

from __future__ import annotations

from collections.abc import Callable
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


def page(title: str, caption: str) -> None:
    st.set_page_config(page_title=f"{title} · Workbench", layout="wide")
    st.title(title)
    st.caption(caption)


def call(handler: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Run a command handler; show its error on the page instead of a traceback."""
    try:
        return handler(*args, **kwargs)
    except (
        LookupError,
        ValueError,
        FileExistsError,
        RuntimeError,
        SystemExit,
    ) as error:
        st.error(f"{type(error).__name__}: {error}")
        return None


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
        return st.text_input("Model string", value=default, key=f"{key}-model-text")
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
