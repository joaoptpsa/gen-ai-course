"""What the case authoring page is editing, kept between reruns.

Lives outside the page script: Streamlit runs a page again on every interaction, and a class
defined there would be a new class each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import yaml

AuthoringState = Literal["new", "loaded", "loaded_lossy"]

BLANK_SCENARIO: dict[str, Any] = {
    "seed": 1,
    "start_time": "10:00",
    "warmup_ticks": 10,
    "ticks_per_action": 1,
    "background_log_lines": 3,
}


def load_text(text: str | None) -> dict[str, Any]:
    parsed = yaml.safe_load(text) if text else None
    return parsed if isinstance(parsed, dict) else {}


@dataclass
class AuthoringSession:
    """One authoring session: a new case, or a loaded one the form can or cannot rewrite.

    A session starts with `blank` or `from_files` and is replaced, never reset, when the author
    loads another case or starts over. Its generation goes into widget keys, so a new session gets
    fresh widgets.
    """

    generation: int
    scenario: dict[str, Any]
    check: dict[str, Any]
    faults: list[dict[str, Any]]
    # The files as loaded, to tell whether the form can rewrite them without losing anything.
    loaded_scenario: str | None = None
    loaded_check: str | None = None
    # What the form would drop from the loaded files. None until measured against the form's
    # first rebuild, which exists only once the form has rendered.
    loss: list[str] | None = None
    fault_adds: int = 0

    @classmethod
    def blank(cls, generation: int) -> AuthoringSession:
        return cls(generation, dict(BLANK_SCENARIO), {}, [])

    @classmethod
    def from_files(
        cls, generation: int, scenario_text: str, check_text: str | None
    ) -> AuthoringSession:
        scenario = load_text(scenario_text)
        faults = list(scenario.get("faults") or [])
        return cls(
            generation,
            scenario,
            load_text(check_text),
            faults,
            loaded_scenario=scenario_text,
            loaded_check=check_text,
        )

    @property
    def state(self) -> AuthoringState:
        if self.loaded_scenario is None:
            return "new"
        if self.loss:
            return "loaded_lossy"
        return "loaded"

    @property
    def loaded_id(self) -> str:
        """The id of the loaded case, or an empty string for a new one."""
        loaded = load_text(self.loaded_scenario)
        return str(loaded.get("id", ""))
