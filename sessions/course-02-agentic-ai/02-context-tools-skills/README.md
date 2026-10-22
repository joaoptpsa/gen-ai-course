# Session 2 — Context Engineering, Tools and Skills

Session 1 produced an agent that only reports recovery when the evidence
supports it. This session adds two difficulties of real operations:

- there is far more information than the agent can use well;
- some tools change the system, and a repeated call can repeat the effect.

Run every command from the repository root after `uv sync` and after setting
`ANTHROPIC_API_KEY` in a local `.env` file.

## What you have

```text
02-context-tools-skills/
├── starter/harness.py        # the agent: context, instructions, output and tools
├── starter/check_actions.py  # calls the restart tool directly, without a model
└── cases/                    # incidents for this session
```

- `build_prompt` in the starter puts every open alert, every log line and every
  runbook in the first message.
- The agent can read metrics and logs, and it has two restart tools.
- Runbooks live in `meridian/data/runbooks/` as markdown files with a version
  and the component versions they apply to. In this session they are your
  procedures (skills).

Look at how much information each case produces before running an agent:

```bash
uv run mrx-chaos run sessions/course-02-agentic-ai/02-context-tools-skills/cases/s02-noisy-gateway.yaml --ticks 5
```

## Exercise 1 — Decide what the agent sees

Run the starter on the noisy incident:

```bash
uv run python -m meridian.run \
  --harness sessions/course-02-agentic-ai/02-context-tools-skills/starter/harness.py \
  --scenario sessions/course-02-agentic-ai/02-context-tools-skills/cases/s02-noisy-gateway.yaml
```

1. Read the trace and the report. Which runbook did the agent follow, which
   tool did it use, and on what target?
2. Copy the starter to `harness_v2.py` and design a context policy:
   - what is always in the first message;
   - what the agent loads only when it needs it, and with which tool;
   - which procedure is loaded, and how the agent knows it applies.
3. Compare both versions on the noisy incident.
4. Run your version on `s02-hidden-config-change.yaml`. If the agent misses
   information that your policy left out, change the policy so the agent can
   still get it, without going back to "everything in the prompt".
5. Ask another group for one extra case and run it too.

## Exercise 2 — Actions that must not happen twice

Check what happens when the same restart is requested twice:

```bash
uv run python sessions/course-02-agentic-ai/02-context-tools-skills/starter/check_actions.py \
  --harness sessions/course-02-agentic-ai/02-context-tools-skills/starter/harness.py
```

1. Redesign the restart tools in your harness: name, description, arguments
   and result. The supplied executor (`meridian/actions.py`) already
   understands an `idempotency_key`; your tool decides whether and how the
   model uses it.
2. Run `check_actions.py` with your harness until a repeated request does not
   produce a second effect, and a reused key with different content is
   refused.
3. Variation: run it again with `--lost-response`, then run your agent on
   `s02-lost-response.yaml`. The first restart is applied but its answer never
   arrives. What should the agent do before trying again?

## Conventions

- Keep a `status` field in the report.
- Do not edit `meridian/`. If your harness needs a tool the simulator already
  offers (see `meridian/tools.py`), expose it from the harness.
- Critical components (`matching-engine`, `reference-db`) cannot be changed by
  this agent. The executor rejects those actions.

## Scope boundary

Context selection, tool interfaces, procedures and idempotent actions inside
one execution. External integrations through MCP are Session 3; memory across
executions is Session 4; permissions and approvals are Session 5; retries and
resuming interrupted work are Session 9.
