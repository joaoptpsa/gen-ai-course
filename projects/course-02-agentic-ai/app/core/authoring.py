"""Validate, serialise and write case (scenario) and check files."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import yaml
from agent.coordination import SECTION as COORDINATION_SECTION
from agent.coordination import validate_coordination

from app.paths import CASES_DIR, CHECKS_DIR
from meridian.agent_runtime import load_identities
from meridian.scenarios import Scenario
from meridian.simulator import Simulator

# The scenario file calls the identifier `id`; the dataclass calls it `scenario_id`.
SCENARIO_KEYS = {
    "id" if field.name == "scenario_id" else field.name
    for field in dataclasses.fields(Scenario)
} - {"path"}

# Keys read by meridian.evaluate.evaluate, plus root_cause, which existing checks carry as documentation,
# and the coordination section, which the workbench judges from team handoffs (agent.coordination).
CHECK_KEYS = {
    "scenario",
    "root_cause",
    "report",
    "required_reads",
    "recovery",
    "forbidden_actions",
    "max_effects",
    "max_tool_calls",
    "forbidden_tool_calls",
    "tickets",
    "memory",
    "approvals",
    "outbound",
    "min_effects",
    "budget",
    "pii",
    "order",
    COORDINATION_SECTION,
}

SCENARIO_REQUIRED_KEYS = ("id", "title", "incident")
CASE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def _field(
    name: str,
    kind: str,
    *,
    required: bool = False,
    choices: list[Any] | None = None,
    default: Any = None,
):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "choices": choices,
        "default": default,
    }


_FAULT_COMMON = [
    _field("at", "int", default=0),
    _field("until", "int"),
    _field("change_id", "str"),
    _field("fault_id", "str"),
]

FAULT_FIELDS: dict[str, list[dict[str, Any]]] = {
    "link": [
        _field("source", "str", required=True),
        _field("target", "str", required=True),
        _field("mode", "choice", choices=["down", "degraded"], default="down"),
        _field("extra_latency_ms", "float", default=0.0),
        *_FAULT_COMMON,
    ],
    "resource": [
        _field("instance", "str", required=True),
        _field(
            "resource", "choice", choices=["memory", "cpu", "disk"], default="memory"
        ),
        _field("rate", "float", default=1.0),
        _field("start_value", "float"),
        *_FAULT_COMMON,
    ],
    "change": [
        _field("effects", "list", default=[]),
        *_FAULT_COMMON,
    ],
    "data": [
        _field("component", "str", default="market-data"),
        _field("delay_ms", "float", default=0.0),
        _field("corrupt", "choice", choices=[False, True], default=False),
        *_FAULT_COMMON,
    ],
    "noise": [
        _field(
            "noise",
            "choice",
            choices=["duplicate_alerts", "false_positive"],
            default="duplicate_alerts",
        ),
        _field("component", "str", default="order-gateway"),
        _field("count", "int", default=1),
        _field("rule", "str", default="latency_high"),
        *_FAULT_COMMON,
    ],
}


def _parse_mapping(text: str, what: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return None, [f"{what} is not valid YAML: {error}"]
    if not isinstance(data, dict):
        return None, [f"{what} must be a YAML mapping, got {type(data).__name__}"]
    return data, []


def _unknown_keys(data: dict[str, Any], known: set[str], what: str) -> list[str]:
    unknown = sorted(str(key) for key in data if key not in known)
    if not unknown:
        return []
    return [
        f"unknown {what} keys: {', '.join(unknown)}; allowed: {', '.join(sorted(known))}"
    ]


def _structure_errors(data: dict[str, Any]) -> list[str]:
    errors = [
        f"missing required key: {key}"
        for key in SCENARIO_REQUIRED_KEYS
        if key not in data
    ]
    # The id becomes the case and check filename, so it must not leave cases/ or checks/.
    if "id" in data and not CASE_ID.fullmatch(str(data["id"])):
        errors.append(
            f"id {data['id']!r} must be lowercase letters, digits and hyphens"
        )
    incident = data.get("incident")
    if "incident" not in data:
        return errors
    if not isinstance(incident, dict):
        return [*errors, "incident must be a mapping with id and summary"]
    errors += [
        f"missing required key: incident.{key}"
        for key in ("id", "summary")
        if key not in incident
    ]
    return errors


def _actor_errors(data: dict[str, Any]) -> list[str]:
    """The runtime stops on an unknown actor role, so catch it before the case is written."""
    actor = data.get("actor") or {}
    role = actor.get("role", "first-line") if isinstance(actor, dict) else None
    roles = load_identities()
    if role in roles:
        return []
    return [f"actor.role {role!r} is unknown; use one of {', '.join(roles)}"]


def _simulation_errors(data: dict[str, Any]) -> list[str]:
    fields = dict(data)
    fields["scenario_id"] = fields.pop("id")
    try:
        Simulator(Scenario(**fields)).advance(1)
    except Exception as error:  # noqa: BLE001 - reported to the author as validation output
        return [f"scenario does not simulate: {type(error).__name__}: {error}"]
    return []


def validate_scenario_text(text: str) -> list[str]:
    data, errors = _parse_mapping(text, "scenario")
    if data is None:
        return errors
    errors = _structure_errors(data) + _unknown_keys(data, SCENARIO_KEYS, "scenario")
    if errors:
        return errors
    return _actor_errors(data) or _simulation_errors(data)


def validate_check_text(text: str, scenario_id: str) -> list[str]:
    data, errors = _parse_mapping(text, "check")
    if data is None:
        return errors
    errors = _unknown_keys(data, CHECK_KEYS, "check")
    if "scenario" not in data:
        return [*errors, "missing required key: scenario"]
    if data["scenario"] != scenario_id:
        errors.append(
            f"check scenario {data['scenario']!r} does not match scenario id {scenario_id!r}"
        )
    if COORDINATION_SECTION in data:
        errors += validate_coordination(data[COORDINATION_SECTION])
    return errors


COMMENT = re.compile(r"(^|\s)#")


def dropped_paths(original: Any, edited: Any, path: str = "") -> list[str]:
    """Keys and list items present in `original` but missing from `edited`, as dotted paths."""
    if isinstance(original, dict):
        if not isinstance(edited, dict):
            return [path or "<root>"]
        return [
            dropped
            for key, value in original.items()
            for dropped in (
                dropped_paths(value, edited[key], f"{path}.{key}" if path else str(key))
                if key in edited
                else [f"{path}.{key}" if path else str(key)]
            )
        ]
    if isinstance(original, list):
        if not isinstance(edited, list):
            return [path]
        missing = [f"{path}[{index}]" for index in range(len(edited), len(original))]
        nested = [
            dropped
            for index, (before, after) in enumerate(zip(original, edited))
            for dropped in dropped_paths(before, after, f"{path}[{index}]")
        ]
        return nested + missing
    return []


def has_comments(text: str) -> bool:
    """Whether YAML text holds comments, which a load-and-dump round trip drops."""
    return any(COMMENT.search(line) for line in text.splitlines())


def round_trip_loss(original_text: str, rebuilt_text: str) -> dict[str, Any]:
    """What rewriting `original_text` as `rebuilt_text` would lose."""
    original = yaml.safe_load(original_text) or {}
    rebuilt = yaml.safe_load(rebuilt_text) or {}
    return {
        "dropped": dropped_paths(original, rebuilt),
        "comments": has_comments(original_text),
    }


def _dump(data: dict[str, Any], first_key: str) -> str:
    ordered = {key: data[key] for key in [first_key] if key in data}
    ordered.update({key: value for key, value in data.items() if key != first_key})
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True)


def scenario_to_yaml(data: dict[str, Any]) -> str:
    return _dump(data, "id")


def check_to_yaml(data: dict[str, Any]) -> str:
    return _dump(data, "scenario")


def write_case(
    scenario_text: str,
    check_text: str | None,
    *,
    force: bool = False,
    cases_dir: Path = CASES_DIR,
    checks_dir: Path = CHECKS_DIR,
) -> dict[str, Any]:
    errors = validate_scenario_text(scenario_text)
    if errors:
        raise ValueError("invalid scenario: " + "; ".join(errors))
    case_id = str(yaml.safe_load(scenario_text)["id"])
    if check_text is not None:
        check_errors = validate_check_text(check_text, case_id)
        if check_errors:
            raise ValueError("invalid check: " + "; ".join(check_errors))

    scenario_path = Path(cases_dir) / f"{case_id}.yaml"
    check_path = (
        Path(checks_dir) / f"{case_id}.yaml" if check_text is not None else None
    )
    targets = [path for path in (scenario_path, check_path) if path is not None]
    if not force:
        for target in targets:
            if target.exists():
                raise FileExistsError(
                    f"{target} already exists; pass force to overwrite"
                )

    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(scenario_text, encoding="utf-8")
    if check_path is not None and check_text is not None:
        check_path.parent.mkdir(parents=True, exist_ok=True)
        check_path.write_text(check_text, encoding="utf-8")
    return {
        "case_id": case_id,
        "scenario_path": str(scenario_path),
        "check_path": str(check_path) if check_path is not None else None,
    }
