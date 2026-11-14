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

- `--offline` runs with a test model: no API calls, no cost. Without it, `run`
  and `compare` call the model from `.env`, or the one given with `--model`.
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

## Layout

- `agent/`: code ported from the session starters and labs, still to be
  adapted. Modules import their siblings by bare name (`import guardrails`), so
  run them with `agent/` on the import path.
- `cases/`, `checks/`: scenarios and their success criteria. Keep the two
  folders side by side: `meridian` looks up a case's check at
  `<case dir>/../checks/<id>.yaml`.
