"""Author a case (scenario and check): a form for the common sections, YAML for the rest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from app import commands
from app.gui import common

COMPONENTS = [
    "order-gateway",
    "matching-engine",
    "market-data",
    "settlement",
    "reference-db",
]
COMPONENT_FIELDS = {"source", "target", "component"}
COMPARATORS = ["<", "<=", ">", ">=", "=="]
LEVELS = ["INFO", "WARN", "ERROR"]
APPROVER_MODES = ["scenario default", "approve_all", "deny_all", "approve_roles"]
CLAIMS = ["not checked", "recovered", "not recovered"]
SCENARIO_FORM_KEYS = {
    "id", "title", "seed", "start_time", "date", "warmup_ticks", "ticks_per_action",
    "background_log_lines", "incident", "changes", "faults", "logs", "alerts", "tools",
    "executor", "approvals", "actor", "approver",
}  # fmt: skip
CHECK_FORM_KEYS = {
    "scenario", "report", "required_reads", "recovery", "forbidden_actions", "max_effects",
    "min_effects", "forbidden_tool_calls", "budget",
}  # fmt: skip
BLANK_SCENARIO: dict[str, Any] = {
    "seed": 1,
    "start_time": "10:00",
    "warmup_ticks": 10,
    "ticks_per_action": 1,
    "background_log_lines": 3,
}


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "text"  # text | int | float | bool | choice
    options: tuple[str, ...] = ()


# Source of the form: the parsed files of the loaded case, or a blank case ---------------


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_text(text: str | None) -> dict[str, Any]:
    parsed = yaml.safe_load(text) if text else None
    return parsed if isinstance(parsed, dict) else {}


def start_from(scenario_text: str | None, check_text: str | None) -> None:
    """Make the form start from these files and bump the widget generation so widgets reset."""
    scenario = load_text(scenario_text) if scenario_text else dict(BLANK_SCENARIO)
    st.session_state["author-source"] = {
        "scenario": scenario,
        "check": load_text(check_text),
    }
    st.session_state["author-gen"] = st.session_state.get("author-gen", 0) + 1
    st.session_state["author-faults"] = list(scenario.get("faults") or [])
    for key in ("yaml-scenario", "yaml-check"):
        st.session_state.pop(key, None)
    if scenario_text:
        st.session_state["yaml-scenario"] = scenario_text
        st.session_state["yaml-check"] = check_text or ""


def source() -> dict[str, dict[str, Any]]:
    if "author-source" not in st.session_state:
        start_from(None, None)
    return st.session_state["author-source"]


def generation() -> int:
    return st.session_state["author-gen"]


def key_of(name: str) -> str:
    return f"{name}-{generation()}"


def render_start() -> None:
    case_ids = [row["case_id"] for row in common.cases()]
    left, middle, right = st.columns([3, 1, 1], vertical_alignment="bottom")
    chosen = left.selectbox(
        "Existing case", case_ids, index=None, key="author-load-choice"
    )
    if middle.button("Load into form", disabled=chosen is None):
        shown = common.call(commands.cases_show, chosen)
        if shown is not None:
            start_from(shown["scenario"], shown["check"])
            st.rerun()
    if right.button("Start blank"):
        start_from(None, None)
        st.rerun()


# Generic list editor ------------------------------------------------------------------


def column_config(column: Column) -> Any:
    if column.kind == "int":
        return st.column_config.NumberColumn(column.name, step=1)
    if column.kind == "float":
        return st.column_config.NumberColumn(column.name)
    if column.kind == "bool":
        return st.column_config.CheckboxColumn(column.name)
    if column.kind == "choice":
        return st.column_config.SelectboxColumn(
            column.name, options=list(column.options)
        )
    return st.column_config.TextColumn(column.name)


def cast_cell(value: Any, kind: str) -> Any:
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return value


def clean_rows(frame: pd.DataFrame, columns: list[Column]) -> list[dict[str, Any]]:
    kinds = {column.name: column.kind for column in columns}
    rows = []
    for record in frame.to_dict("records"):
        row = {
            name: cast_cell(value, kinds[str(name)])
            for name, value in record.items()
            if not pd.isna(value) and value != ""
        }
        if row:
            rows.append(row)
    return rows


def typed_frame(rows: list[dict[str, Any]], columns: list[Column]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=[column.name for column in columns])
    numeric = {
        column.name: float for column in columns if column.kind in ("int", "float")
    }
    text = {column.name: object for column in columns if column.name not in numeric}
    return frame.astype({**numeric, **text})


def list_editor(
    name: str, rows: list[dict[str, Any]], columns: list[Column]
) -> list[dict[str, Any]]:
    frame = typed_frame(rows, columns)
    edited = st.data_editor(
        frame,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={column.name: column_config(column) for column in columns},
        key=key_of(name),
    )
    return clean_rows(edited, columns)


def component_column(name: str = "component") -> Column:
    return Column(name, "choice", tuple(COMPONENTS))


# Scenario form ------------------------------------------------------------------------


def scenario_metadata(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Metadata")
    left, right = st.columns(2)
    case_id = left.text_input(
        "Case id", value=str(scenario.get("id", "")), key=key_of("id")
    )
    title = right.text_input(
        "Title", value=str(scenario.get("title", "")), key=key_of("title")
    )
    columns = st.columns(6)
    seed = columns[0].number_input(
        "Seed", value=int(scenario.get("seed", 1)), step=1, key=key_of("seed")
    )
    start = columns[1].text_input(
        "Start time",
        value=str(scenario.get("start_time", "10:00")),
        key=key_of("start"),
    )
    warmup = columns[2].number_input(
        "Warmup ticks",
        value=int(scenario.get("warmup_ticks", 10)),
        min_value=0,
        key=key_of("warmup"),
    )
    per_action = columns[3].number_input(
        "Ticks per action",
        value=int(scenario.get("ticks_per_action", 1)),
        min_value=1,
        key=key_of("per-action"),
    )
    background = columns[4].number_input(
        "Background log lines",
        value=int(scenario.get("background_log_lines", 3)),
        min_value=0,
        key=key_of("background"),
    )
    date = columns[5].text_input(
        "Date",
        value=str(scenario.get("date", "")),
        key=key_of("date"),
        placeholder="2026-11-04",
    )
    metadata: dict[str, Any] = {
        "id": case_id,
        "title": title,
        "seed": int(seed),
        "start_time": start,
        "warmup_ticks": int(warmup),
        "ticks_per_action": int(per_action),
        "background_log_lines": int(background),
    }
    if date:
        metadata["date"] = date
    return metadata


def scenario_incident(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Incident")
    incident = scenario.get("incident") or {}
    left, middle, right = st.columns([1, 3, 2])
    incident_id = left.text_input(
        "Incident id", value=str(incident.get("id", "")), key=key_of("inc-id")
    )
    summary = middle.text_input(
        "Summary", value=str(incident.get("summary", "")), key=key_of("inc-summary")
    )
    alert = right.text_input(
        "Alert",
        value=str(incident.get("alert", "")),
        key=key_of("inc-alert"),
        placeholder="latency_high/order-gateway",
    )
    result = {"id": incident_id, "summary": summary}
    if alert:
        result["alert"] = alert
    return {"incident": result}


def scenario_changes(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Changes")
    columns = [
        Column("change_id"),
        component_column(),
        Column("kind", "choice", ("config", "deploy", "rollout")),
        Column("description"),
        Column("at", "int"),
    ]
    rows = list_editor("changes", scenario.get("changes") or [], columns)
    return {"changes": rows} if rows else {}


# Faults: chosen by type, fields generated from the schema.


def optional_number(label: str, kind: str, key: str) -> int | float | None:
    text = st.text_input(f"{label} (optional)", key=key)
    if not text.strip():
        return None
    try:
        return int(text) if kind == "int" else float(text)
    except ValueError:
        st.error(f"{label} must be a number")
        return None


def fault_field_widget(spec: dict[str, Any], key: str) -> Any:
    name, kind, default = spec["name"], spec["kind"], spec["default"]
    if kind == "choice":
        choices = spec["choices"]
        return st.selectbox(name, choices, index=choices.index(default), key=key)
    if kind == "list":
        return effects_editor(key)
    if kind in ("int", "float") and default is None:
        return optional_number(name, kind, key)
    if kind == "int":
        return int(st.number_input(name, value=int(default), step=1, key=key))
    if kind == "float":
        return float(st.number_input(name, value=float(default), key=key))
    if name in COMPONENT_FIELDS:
        options = COMPONENTS
        index = options.index(default) if default in options else 0
        return st.selectbox(name, options, index=index, key=key)
    return st.text_input(name, value=default or "", key=key)


def effects_editor(key: str) -> list[dict[str, Any]]:
    st.caption("change.effects")
    columns = [
        component_column(),
        Column("error_rate", "float"),
        Column("latency_ms", "float"),
        Column("reason"),
    ]
    frame = typed_frame([], columns)
    edited = st.data_editor(
        frame,
        num_rows="dynamic",
        hide_index=True,
        column_config={column.name: column_config(column) for column in columns},
        key=key,
    )
    return clean_rows(edited, columns)


def fault_from_widgets(
    fault_type: str, fields: list[dict[str, Any]], suffix: str
) -> dict[str, Any]:
    fault: dict[str, Any] = {"type": fault_type}
    for spec in fields:
        value = fault_field_widget(spec, f"fault-{fault_type}-{spec['name']}-{suffix}")
        if value in (None, "", []) or (
            value == spec["default"] and not spec["required"]
        ):
            continue
        fault[spec["name"]] = value
    return fault


def faults_list() -> list[dict[str, Any]]:
    return st.session_state["author-faults"]


def render_fault_rows() -> None:
    for index, fault in enumerate(faults_list()):
        text, button = st.columns([6, 1], vertical_alignment="center")
        text.code(
            yaml.safe_dump(fault, default_flow_style=True, sort_keys=False).strip(),
            language="yaml",
        )
        if button.button("Remove", key=f"rm-fault-{generation()}-{index}"):
            faults_list().pop(index)
            st.rerun()


def render_fault_adder(schema: dict[str, Any]) -> None:
    fault_fields = schema["fault_fields"]
    with st.expander("Add a fault"):
        fault_type = st.selectbox(
            "Fault type", list(fault_fields), key=key_of("fault-type")
        )
        if fault_type is None:
            return
        suffix = f"{generation()}-{st.session_state.get('fault-adds', 0)}"
        fault = fault_from_widgets(fault_type, fault_fields[fault_type], suffix)
        if st.button("Add fault", key=key_of("fault-add")):
            faults_list().append(fault)
            st.session_state["fault-adds"] = st.session_state.get("fault-adds", 0) + 1
            st.rerun()


def scenario_faults(schema: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Faults")
    render_fault_rows()
    render_fault_adder(schema)
    return {"faults": list(faults_list())} if faults_list() else {}


def scenario_logs(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Scripted logs")
    columns = [
        Column("at", "int"),
        component_column(),
        Column("level", "choice", tuple(LEVELS)),
        Column("message"),
    ]
    rows = list_editor("logs", scenario.get("logs") or [], columns)
    return {"logs": rows} if rows else {}


def scenario_alerts(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Scripted alerts")
    columns = [
        Column("at", "int"),
        Column("rule"),
        component_column(),
        Column("auto_resolve", "bool"),
    ]
    rows = list_editor("alerts", scenario.get("alerts") or [], columns)
    return {"alerts": rows} if rows else {}


def tool_rows(tools: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "tool": name,
            "fail_calls": ", ".join(
                str(call) for call in (setting or {}).get("fail_calls", [])
            ),
            "unavailable": (setting or {}).get("unavailable") or None,
        }
        for name, setting in tools.items()
    ]


def tools_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for row in rows:
        setting: dict[str, Any] = {}
        calls = [
            part.strip()
            for part in str(row.get("fail_calls", "")).split(",")
            if part.strip()
        ]
        if calls:
            setting["fail_calls"] = [int(call) for call in calls if call.isdigit()]
        if row.get("unavailable"):
            setting["unavailable"] = True
        if "tool" in row and setting:
            tools[row["tool"]] = setting
    return tools


def scenario_tools(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Tool behaviour")
    st.caption("fail_calls: comma separated call numbers that fail, e.g. 1, 3")
    columns = [Column("tool"), Column("fail_calls"), Column("unavailable", "bool")]
    rows = list_editor("tools", tool_rows(scenario.get("tools") or {}), columns)
    tools = tools_from_rows(rows)
    return {"tools": tools} if tools else {}


def scenario_executor(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Executor: dropped responses")
    executor = dict(scenario.get("executor") or {})
    columns = [Column("action"), Column("call", "int")]
    rows = list_editor("drops", executor.get("drop_response") or [], columns)
    executor.pop("drop_response", None)
    if rows:
        executor["drop_response"] = rows
    return {"executor": executor} if executor else {}


def scenario_approvals(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Approvals")
    rows = [{"approval": reference} for reference in scenario.get("approvals") or []]
    edited = list_editor("approvals", rows, [Column("approval")])
    references = [row["approval"] for row in edited]
    return {"approvals": references} if references else {}


def scenario_identity(scenario: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Actor and approver")
    left, middle, right = st.columns(3)
    role = left.text_input(
        "Actor role",
        value=str((scenario.get("actor") or {}).get("role", "")),
        key=key_of("actor"),
        placeholder="first-line",
    )
    approver = scenario.get("approver") or {}
    current = approver.get("mode") or (
        "approve_roles" if "approve_roles" in approver else "scenario default"
    )
    mode = middle.selectbox(
        "Approver mode",
        APPROVER_MODES,
        index=APPROVER_MODES.index(current),
        key=key_of("approver-mode"),
    )
    result: dict[str, Any] = {}
    if role:
        result["actor"] = {"role": role}
    if mode == "approve_roles":
        roles = right.text_input(
            "Approver roles (comma separated)",
            value=", ".join(approver.get("approve_roles", [])),
            key=key_of("approver-roles"),
        )
        result["approver"] = {
            "approve_roles": [part.strip() for part in roles.split(",") if part.strip()]
        }
    elif mode != "scenario default":
        result["approver"] = {"mode": mode}
    return result


def scenario_passthrough(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in scenario.items() if key not in SCENARIO_FORM_KEYS
    }


def scenario_form(schema: dict[str, Any]) -> dict[str, Any]:
    scenario = source()["scenario"]
    sections = [
        scenario_metadata(scenario),
        scenario_incident(scenario),
        scenario_changes(scenario),
        scenario_faults(schema),
        scenario_logs(scenario),
        scenario_alerts(scenario),
        scenario_tools(scenario),
        scenario_executor(scenario),
        scenario_approvals(scenario),
        scenario_identity(scenario),
        scenario_passthrough(scenario),
    ]
    merged: dict[str, Any] = {}
    for section in sections:
        merged.update(section)
    return merged


# Check form ---------------------------------------------------------------------------


def check_report(check: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Report")
    report = dict(check.get("report") or {})
    claims = report.pop("claims_recovery", None)
    mentions = report.pop("must_mention", None) or []
    current = CLAIMS[0] if claims is None else CLAIMS[1 if claims else 2]
    left, right = st.columns(2)
    choice = left.selectbox(
        "Claims recovery", CLAIMS, index=CLAIMS.index(current), key=key_of("claims")
    )
    text = right.text_area(
        "Must mention (one per line)", value="\n".join(mentions), key=key_of("mentions")
    )
    if choice != CLAIMS[0]:
        report["claims_recovery"] = choice == CLAIMS[1]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        report["must_mention"] = lines
    return {"report": report} if report else {}


def check_reads(check: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Required reads")
    rows = list_editor(
        "reads", check.get("required_reads") or [], [Column("tool"), component_column()]
    )
    return {"required_reads": rows} if rows else {}


def check_recovery(check: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Recovery")
    recovery = check.get("recovery") or {}
    hold = st.number_input(
        "Hold ticks",
        value=int(recovery.get("hold_ticks", 5)),
        min_value=1,
        key=key_of("hold"),
    )
    columns = [
        component_column(),
        Column("metric"),
        Column("op", "choice", tuple(COMPARATORS)),
        Column("value", "float"),
        Column("link"),
        Column("state", "choice", ("up", "down")),
    ]
    conditions = list_editor("conditions", recovery.get("conditions") or [], columns)
    return (
        {"recovery": {"hold_ticks": int(hold), "conditions": conditions}}
        if conditions
        else {}
    )


def check_effects(check: dict[str, Any], name: str, title: str) -> dict[str, Any]:
    st.subheader(title)
    columns = [Column("action"), Column("target")]
    if name != "forbidden_actions":
        columns.append(Column("count", "int"))
    rows = list_editor(name, check.get(name) or [], columns)
    return {name: rows} if rows else {}


def check_forbidden_tools(check: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Forbidden tool calls")
    rows = list_editor(
        "forbidden-tools", check.get("forbidden_tool_calls") or [], [Column("tool")]
    )
    return {"forbidden_tool_calls": rows} if rows else {}


def check_budget(check: dict[str, Any]) -> dict[str, Any]:
    st.subheader("Budget")
    budget = dict(check.get("budget") or {})
    tokens = st.number_input(
        "Max input tokens (0 for no limit)",
        value=int(budget.get("max_input_tokens", 0)),
        min_value=0,
        step=1000,
        key=key_of("tokens"),
    )
    budget.pop("max_input_tokens", None)
    if tokens:
        budget["max_input_tokens"] = int(tokens)
    return {"budget": budget} if budget else {}


def check_form(case_id: str) -> dict[str, Any]:
    check = source()["check"]
    sections = [
        check_report(check),
        check_reads(check),
        check_recovery(check),
        check_effects(check, "forbidden_actions", "Forbidden actions"),
        check_effects(check, "max_effects", "Max effects"),
        check_effects(check, "min_effects", "Min effects"),
        check_forbidden_tools(check),
        check_budget(check),
    ]
    passthrough = {
        key: value for key, value in check.items() if key not in CHECK_FORM_KEYS
    }
    merged: dict[str, Any] = {"scenario": case_id, **passthrough}
    for section in sections:
        merged.update(section)
    return merged


# Validate and write -------------------------------------------------------------------


def case_id_of(text: str) -> str:
    return str(load_text(text).get("id", ""))


def show_validation(result: dict[str, Any]) -> None:
    if result["valid"]:
        st.success(f"Valid case `{result['case_id']}`")
        return
    for error in result["scenario_errors"]:
        st.error(f"scenario: {error}")
    for error in result["check_errors"]:
        st.error(f"check: {error}")


def write_unless_exists(
    scenario_text: str, check_text: str, force: bool
) -> dict[str, Any] | None:
    try:
        return commands.cases_write(scenario_text, check_text, force=force)
    except FileExistsError as error:
        st.warning(f"{error}. Tick the overwrite box to replace it.")
        return None


def show_written(written: dict[str, Any]) -> None:
    common.cases.clear()
    st.success(f"Wrote `{written['scenario_path']}` and `{written['check_path']}`")
    st.page_link(
        "pages/1_Scenario_explorer.py", label="Preview in the scenario explorer"
    )


def render_actions(scenario_text: str, check_text: str, prefix: str) -> None:
    case_id = case_id_of(scenario_text) or "<id>"
    common.cli_hint(
        f"cases validate cases/{case_id}.yaml --check checks/{case_id}.yaml"
    )
    common.cli_hint(f"cases write cases/{case_id}.yaml --check checks/{case_id}.yaml")
    # Offered before writing, so replacing an existing case is always a deliberate choice.
    existing = {row["case_id"] for row in common.cases()}
    overwrite = False
    if case_id in existing:
        overwrite = st.checkbox(
            f"Overwrite existing case {case_id}", key=f"{prefix}-overwrite"
        )
    left, right = st.columns(2)
    if left.button("Validate", key=f"{prefix}-validate"):
        result = common.call(commands.cases_validate, scenario_text, check_text)
        if result is not None:
            show_validation(result)
    if right.button("Write", key=f"{prefix}-write", type="primary"):
        written = common.call(write_unless_exists, scenario_text, check_text, overwrite)
        if written is not None:
            show_written(written)


# Tabs ---------------------------------------------------------------------------------


def reset_yaml_from_form(scenario_text: str, check_text: str) -> None:
    st.session_state["yaml-scenario"] = scenario_text
    st.session_state["yaml-check"] = check_text


def render_form_tab(schema: dict[str, Any]) -> tuple[str, str]:
    scenario = scenario_form(schema)
    check = check_form(str(scenario.get("id", "")))
    scenario_text, check_text = dump_yaml(scenario), dump_yaml(check)
    left, right = st.columns(2)
    left.markdown("**Scenario YAML**")
    left.code(scenario_text, language="yaml")
    right.markdown("**Check YAML**")
    right.code(check_text, language="yaml")
    render_actions(scenario_text, check_text, "form")
    return scenario_text, check_text


def render_yaml_tab(form_scenario: str, form_check: str) -> None:
    st.session_state.setdefault("yaml-scenario", form_scenario)
    st.session_state.setdefault("yaml-check", form_check)
    st.caption(
        "Advanced sections (tickets, mcp, memory_seed, check tickets, memory, pii, outbound, approvals) are edited here."
    )
    st.button(
        "Reset from form",
        on_click=reset_yaml_from_form,
        args=(form_scenario, form_check),
    )
    left, right = st.columns(2)
    scenario_text = left.text_area("Scenario", height=500, key="yaml-scenario")
    check_text = right.text_area("Check", height=500, key="yaml-check")
    render_actions(scenario_text, check_text, "yaml")


common.page(
    "Case authoring",
    "Build or edit a scenario and its check, validate them, then write them to cases/ and checks/.",
)
authoring_schema = common.call(commands.authoring_schema)
render_start()
if authoring_schema is not None:
    form_tab, yaml_tab = st.tabs(["Form", "YAML"])
    with form_tab:
        generated_scenario, generated_check = render_form_tab(authoring_schema)
    with yaml_tab:
        render_yaml_tab(generated_scenario, generated_check)
