# Course 2 — Agentic AI: project

The evolving project for Course 2: an incident-response system for the
Meridian Exchange, a fictional stock exchange simulated locally.

It grows in three milestones:

1. First-Line Incident Agent (sessions 1–3)
2. Production On-Call Agent (sessions 4–6)
3. 24/7 Incident Response Center (sessions 7–9)

Milestone briefs will live in `milestones/`.

## Layout

- `agent/`: code ported from the session starters and labs, still to be
  adapted. Modules import their siblings by bare name (`import guardrails`), so
  run them with `agent/` on the import path.
- `cases/`, `checks/`: scenarios and their success criteria. Keep the two
  folders side by side: `meridian` looks up a case's check at
  `<case dir>/../checks/<id>.yaml`.
- `decks/`: the course decks (`pdf/`) and their Markdown transcriptions
  (`md/`). The project brief is `decks/md/Projeto Agentic AI.md`.
