# Course 2 — Agentic AI: project

An incident-response system for the Meridian Exchange, a fictional stock
exchange simulated locally. The brief, with its three milestones, is
`decks/md/Projeto Agentic AI.md`.

## Workbench

`bin/mrx-project` explores cases, runs and compares harnesses, tracks the
brief's requirements and writes cases. It works from any directory; the
examples run from this folder.

```bash
bin/mrx-project --help   # every command and subcommand takes --help
bin/mrx-project gui      # the same actions in a Streamlit GUI

# What there is to run, and what a case does without an agent.
bin/mrx-project cases list
bin/mrx-project harnesses list
bin/mrx-project explore s01-gateway-latency --ticks 30

# One harness on one case.
bin/mrx-project run 01-agent-harness/harness s01-gateway-latency --offline

# Several harnesses on several cases (every case without --case), saved as a set.
bin/mrx-project compare --harness 01-agent-harness/harness --harness 01-agent-harness/harness_v2 \
  --case s01-gateway-latency --case s01-stale-alert --offline --save baseline

# Saved sets: list them, show one, diff two. compare --baseline <set-id> diffs as it runs.
bin/mrx-project results list
bin/mrx-project results show <set-id>
bin/mrx-project results diff <baseline-set-id> <current-set-id>

# The brief's requirements against the saved runs of their evidence cases.
bin/mrx-project requirements status
bin/mrx-project requirements evidence add <requirement-id> <case-id>
bin/mrx-project requirements note <requirement-id> "text"

# A new case: check it, then copy it into cases/ and checks/.
bin/mrx-project cases validate my-case.yaml --check my-check.yaml
bin/mrx-project cases write my-case.yaml --check my-check.yaml
```

The self-improving team (see `docs/self-improvement.md`) runs offline, with no
API calls, through the `offline` model:

```bash
# The team on one case; --memory keeps lessons between runs in a SQLite file.
bin/mrx-project run project/team s01-gateway-latency --model offline --memory /tmp/lessons.db

# Every run copies the snapshot frozen: no run learns, and the source stays unchanged.
bin/mrx-project compare --harness project/team --model offline --reps 2 --workers 4 \
  --memory-snapshot /tmp/lessons.db --save team-snapshot

# Critic's blame for one saved run, then a training case drafted from it (nothing is written).
bin/mrx-project results review <set-id> <run-id>
bin/mrx-project cases draft <set-id> <run-id> [--span <span-id>] [--model offline|<model>] [--approve-live]

# One candidate attempt for one agent, then the held-out test of a team.
bin/mrx-project improve run --role network --model offline --reps 1 [--memory-snapshot /tmp/lessons.db]
bin/mrx-project improve test --version <team fingerprint or team.yaml> --model offline
```

- `--offline` runs with a test model: no API calls, no cost. Without it, `run`
  and `compare` call the model from `.env`, or the one given with `--model`.
- `--model offline` is a deterministic stand-in for every agent of the team
  (`agent/offline.py`): no API key, no cost, and it finishes every case. It is
  not the `--offline` flag, which uses pydantic's test model for the session
  harnesses. Live models in `improve`, `results review` and `cases draft` need
  `--approve-live`, and `--cap-usd` (default 5.00) stops spending.
- Lessons: with `--memory` or `--memory-snapshot` each role gets
  `read_lessons`, `cite_lessons` and `propose_lesson` tools. After the run is
  evaluated, lessons it cited are confirmed, and the lessons the team proposed
  are kept. A snapshot is frozen, so it is read but never changed. Without
  either option a run keeps no lessons. A run record has `memory_fingerprint`
  (the memory it started with) and `lessons` (what was cited and settled).
  After a failed run, a lesson cited by a role whose role check failed is
  retired, with the check name and span ids as evidence.
- `--max-requests` defaults to the harness's `DEFAULT_MAX_REQUESTS` (40 for the
  team, which makes lessons fit) and else to 20; a run record keeps the limit.
- `improve run` appends every attempt to `harnesses/versions/lineage.jsonl` and
  never edits `harnesses/team.yaml`; a kept version is a new file under
  `harnesses/versions/<role>/`, and a human pins it. With `--memory-snapshot`
  it first copies the file without the lessons of test-split cases, whose
  `source_ref` is `<run>@<case>`.
- `cases draft` takes a saved failing run of a training case only, and prints a
  case and a check with a `coordination:` section, the source ids and a
  rehearsal of a good and a failing trajectory. Review the YAML, then admit it
  with `cases write`. A check with a `coordination:` section is judged on the
  team's handoffs, so other harnesses fail it explicitly.
- `--json` prints any command's result as JSON. In a run record read `outcome`
  (`passed`, `failed`, `not_evaluated` or `errored`), not `passed`: that is the
  evaluation's verdict and can be true for a run that ended without a report.
- A file in `harnesses/` that defines `build_agent(model)` is listed as
  `project/<file name>`. The session harnesses are read-only baselines.
- `--save` writes to `results/`, which is committed as evidence. Tool results
  over 2000 characters are truncated there.
- The workbench rewrites `requirements.yaml`, so it holds no comments.
- A new action starts as a handler in `app/commands.py`; `app/cli.py` and the
  GUI only call it.

## Tracing

Every run is traced with OpenTelemetry (`app/core/telemetry.py`): PydanticAI's
agent, model and tool spans under one `workbench.run` root, with personal data
masked. `--save` writes each run's spans to
`results/<set id>/<run id>.spans.json`, in the session 8 lab's trace format.
Runs also export over OTLP whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

`telemetry/docker-compose.yml` runs Tempo, which stores traces, and Grafana,
which shows them, both on 127.0.0.1:

```bash
docker compose --file telemetry/docker-compose.yml up --detach
```

Grafana is at <http://127.0.0.1:3000>, with no login. The "Meridian workbench"
dashboard shows runs, verdicts, cost in dollars, duration, and cost, tokens and
tool calls per agent, filtered by harness, case and model; Explore opens single
traces. Tempo takes OTLP on port 14318, since a workstation collector may
already hold 4318; to send runs there, set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318`. Traces are kept 14 days,
Tempo's default. Adding `down --volumes` to the same command stops the stack
and deletes its traces.

- Cost comes from PydanticAI, which prices each model call through
  `genai-prices` (`operation.cost`). The runner adds each run's totals to its
  root span and writes one `meridian.agent_usage` span per agent; the offline
  test model has no price, so its runs cost nothing.
- The dashboard is inline in the compose file. Change it in
  `telemetry/build_dashboard.py` and run that script; it rewrites the inline
  JSON.
- Compose does not notice edits to inline configs: after changing one, run
  `up --detach --force-recreate` with the service name.

## Layout

- `agent/`: code ported from the session starters and labs, still to be
  adapted. Modules import their siblings by bare name (`import guardrails`), so
  run them with `agent/` on the import path.
- `docs/self-improvement.md`: design of the self-improving multi-agent team
  and its OpenTelemetry tracing and export.
- `telemetry/`: the local Tempo and Grafana stack (see Tracing).
- `cases/`, `checks/`: scenarios and their success criteria. Keep the two
  folders side by side: `meridian` looks up a case's check at
  `<case dir>/../checks/<id>.yaml`.

## Provisional Checks

The session 5 to 9 labs ship scenarios but no checks, so the checks of the
`s05-` to `s09-` cases were written from each lab's README and code. The
`ext-` cases adapt public postmortems; `cases/SOURCES.md` holds each source and
the facts the case relies on, and their checks are our reading of the source.
Every one of these checks opens with a `# PROVISIONAL` comment;
`grep -l PROVISIONAL checks/` lists the ones still waiting for the
instructor's material.

| Case | Assumption to confirm |
| --- | --- |
| `s05-*` | The lab's per-exercise user request lives in `incident.summary`; its controls are the harness's job. |
| `s07-site-a-carrier` | The lab's fix is moving order-gateway to site C; site B (in maintenance) is the wrong failover. |
| `s08-resume-lost-response` | The lab's crash becomes a lost rollback response on a change that needs the incident manager's approval. A blind second rollback has no effect in the simulator, so the check cannot catch one. |
| `s09-alert-storm` | `budget.max_input_tokens: 60000` is an estimate, not a measured limit. |
| `ext-*` | Each adaptation's comment says what it keeps and drops from the source. "Halt" or "do not reopen" decisions become a message and no recovery claim, since the simulator has no halt. |

`must_not_mention` matches substrings, so "not a DDoS" contains "DDoS". These
checks only ban phrases whose mere presence is wrong (such as "no impact" in a
customer message); a wrong theory or claim the agent could also negate is left
unchecked.

When the instructor publishes solutions (scenario solutions under
`private/course-02-agentic-ai/solutions/<case id>.yaml`, lab references under
`private/course-02-agentic-ai/reference/session-0N/`):

1. Compare each provisional check with the instructor's criteria and update
   it, or replace it with the instructor's file.
1. A check in `checks/` hides a private solution with the same id, because
   `meridian` reads the public file first (`find_solution` in
   `meridian/agent_runtime.py`). A stale provisional check would keep the
   instructor's solution from ever being used.
1. Rerun the saved sets that include these cases: their verdicts came from the
   provisional criteria.
1. Remove the `# PROVISIONAL` comment.
