# Course 2 — Agentic AI: project

The evolving project for Course 2: an incident-response system for the
Meridian Exchange, a fictional stock exchange simulated locally.

It grows in three milestones:

1. First-Line Incident Agent (sessions 1–3)
2. Production On-Call Agent (sessions 4–6)
3. 24/7 Incident Response Center (sessions 7–9)

Milestone briefs will live in `milestones/`.

## Workbench

A CLI and a Streamlit GUI to explore cases, run and compare harnesses, track the
brief's requirements and author cases. Run from anywhere in the repository:

```text
projects/course-02-agentic-ai/bin/mrx-project --help
projects/course-02-agentic-ai/bin/mrx-project gui
```

Every GUI action calls the same handler in `app/commands.py` as its CLI
subcommand, and each page shows the equivalent command. Add new actions there
first, then expose them in `app/cli.py` and the GUI. `--offline` (the "offline
test model" in the GUI) runs harnesses without API calls.

- `harnesses/`: project agent versions, each a file defining
  `build_agent(model)`. The session harnesses are listed as read-only
  baselines.
- `results/`: saved result sets, committed as evidence. Tool results longer
  than 2000 characters are truncated in saved sets.
- Run records (`--json`, saved sets) carry `outcome`: `passed`, `failed`,
  `not_evaluated` or `errored`. Read it instead of `passed`, which is the
  evaluation's verdict and can be true for a run that ended without a report.
- `requirements.yaml`: the brief's requirements, criteria and deliverables
  with their evidence cases. The workbench rewrites it, so it holds no
  comments.

## Layout

- `agent/`: code ported from the session starters and labs, still to be
  adapted. Modules import their siblings by bare name (`import guardrails`), so
  run them with `agent/` on the import path.
- `cases/`, `checks/`: scenarios and their success criteria. Keep the two
  folders side by side: `meridian` looks up a case's check at
  `<case dir>/../checks/<id>.yaml`.
- `decks/`: the course decks (`pdf/`) and their Markdown transcriptions
  (`md/`). The project brief is `decks/md/Projeto Agentic AI.md`.
