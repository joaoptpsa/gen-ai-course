# Session 4 — Memory as a Data System

Until now every run started from nothing. An on-call agent works in shifts:
it should know about earlier incidents, known problems and what the previous
shift left open. This session adds memory between runs and treats it as data:
it has an origin, a confidence, a validity, owners, corrections and deletions.

Memory never replaces the current state of the systems. Metrics, changes and
tickets are the operational source of truth; memory is a hint about where to
look.

Run every command from the repository root after `uv sync` and after setting
`ANTHROPIC_API_KEY` in a local `.env` file.

## What you have

```text
04-memory/
├── starter/harness.py        # the agent, with remember/recall tools and no memory policy
├── starter/check_memory.py   # calls your memory tools directly, without a model
└── cases/                    # incidents for this session
```

- `meridian/memory.py` is the supplied store (SQLite). Each record has a kind,
  a subject, the content, its origin (`source_type`: user, agent, tool or
  document, and `source_ref`), author, team, creation time, optional
  `valid_until`, a confidence and a status (`active` or `superseded`).
  Read its docstring.
- `deps.memory` is the store and `deps.identity` is who the agent acts as
  (role, name and team, from `meridian/data/identities.yaml`).
- Some cases start with memories from earlier shifts (`memory_seed` in the
  scenario file).
- A harness can define `after_run(report, deps)`. The runner calls it when the
  agent finishes, for example to write a handover note.

The runner's memory options:

```bash
# default: a fresh store per run, with the scenario's memories from earlier shifts
uv run python -m meridian.run --harness <harness.py> --scenario <case.yaml>
# one store kept across runs, in the order given
uv run python -m meridian.run --harness <harness.py> --scenario day1.yaml --scenario day2.yaml --memory runs/s04-memory.db
# no memory at all
uv run python -m meridian.run --harness <harness.py> --scenario day2.yaml --no-memory
```

A store given with `--memory` keeps everything between commands. Use a new
file name for each experiment, and one harness per command.

## Exercise 1 — A memory policy

Run the starter on the first two cases:

```bash
uv run python -m meridian.run \
  --harness sessions/course-02-agentic-ai/04-memory/starter/harness.py \
  --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-stale-false-positive.yaml \
  --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-conflicting-shift-notes.yaml
```

1. In each trace, find the memory the agent relied on. Was it true at the
   time it was written? Is it true now? How could the agent have known?
2. Copy the starter to `harness_v2.py` and write a memory policy as code and
   as a short section in your README:
   - **write**: what is saved, by whom, with which kind, subject, confidence
     and validity;
   - **origin**: what each source may write. A user, the agent, a tool result
     and a document (such as a ticket) are not equally trusted;
   - **recall**: what is returned to the model and how it is presented
     (origin, age, confidence), and what must still be checked against the
     current state before acting;
   - **conflicts**: what happens when two memories disagree, and how a
     correction replaces an older record (`supersedes`).
3. Run both cases again, then `s04-ticket-copied-note`: a ticket asks the
   agent to save a "standard fix". Check what ends up in memory.

## Exercise 2 — Lifecycle: corrections, deletion, isolation and handover

```bash
uv run python sessions/course-02-agentic-ai/04-memory/starter/check_memory.py \
  --harness sessions/course-02-agentic-ai/04-memory/starter/harness.py
```

1. Make every check pass with your harness:
   - a team never sees another team's memories;
   - a superseded record is not returned as current;
   - an expired record is not returned as current;
   - `forget(ctx, memory_id, reason)` deletes a record so that it cannot be
     recalled, and the store keeps only a log of the deletion.
2. Add a shift handover with `after_run`: what one run hands to the next, and
   what the next run must check again before trusting it.
3. Compare with and without memory on the same tasks:

   ```bash
   uv run python -m meridian.run --harness <your harness> --summary \
     --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-recurring-leak-day1.yaml \
     --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-recurring-leak-day2.yaml \
     --memory runs/s04-with-memory.db
   uv run python -m meridian.run --harness <your harness> --summary \
     --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-recurring-leak-day1.yaml \
     --scenario sessions/course-02-agentic-ai/04-memory/cases/s04-recurring-leak-day2.yaml \
     --no-memory
   ```

   Does memory change the result on day 2, or only the number of steps and
   tokens? Is the difference worth what you store?
4. Ask another group for one memory case (a scenario with `memory_seed`) and
   defend your write and recall rules against it.

## Conventions

- Keep a `status` field in the report.
- Do not edit `meridian/`. The store and its queries are supplied; the policy
  is yours.
- Memories are not checkpoints. Resuming an interrupted incident is Session 9.

## Scope boundary

The life cycle of information between runs: writing, origin, confidence,
validity, conflicts, corrections, deletion, isolation and handover. A
poisoned memory as an attack vector is Session 5. Do not build a database or
a vector search.
