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
