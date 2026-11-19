"""The multi-agent incident team as a workbench harness (see agent/team.py).

The team's design (topology and one version file per role) comes from `team.yaml`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
# The project folder has a hyphen, so `agent` is not importable until it is on the path.
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from agent.lessons import LessonDraft, LessonUse
from agent.team import TeamAgent, build_team_agent, run_sync, scratch_state
from agent.team_tools import Handoff
from agent.versions import TeamVersion, load_team

from meridian.agent_runtime import IncidentDeps

# The limit covers every role of one run; lessons add a request or two per role.
DEFAULT_MAX_REQUESTS = 40
TEAM_FILE = Path(__file__).with_name("team.yaml")


def resolved_team() -> TeamVersion:
    return load_team(TEAM_FILE)


def build_agent(model: Any) -> TeamAgent:
    return build_team_agent(model, resolved_team())


def run_attributes() -> dict[str, str]:
    team = resolved_team()
    return {
        "meridian.team_version": team.fingerprint,
        "meridian.topology": team.topology,
    }


def run_agent(
    agent: TeamAgent,
    prompt: str,
    *,
    deps: IncidentDeps,
    usage_limits: Any,
    toolsets: Any,
) -> Any:
    return run_sync(agent, prompt, deps, usage_limits, toolsets)


def run_handoffs(scratch: dict[str, Any]) -> list[Handoff]:
    """The handoffs the team recorded, for coordination checks."""
    state = scratch_state(scratch)
    return [] if state is None else state.handoffs


def lesson_evidence(
    scratch: dict[str, Any],
) -> tuple[list[LessonUse], list[LessonDraft]]:
    """The lessons the roles cited and the lessons they propose, for settlement after evaluation."""
    state = scratch_state(scratch)
    if state is None:
        return [], []
    return state.lesson_uses(), list(state.drafts)
