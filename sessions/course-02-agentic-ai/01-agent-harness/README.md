# Session 1 — Agent Harnesses and PydanticAI

The Meridian Exchange is a fictional stock exchange that runs in a local
simulator (`meridian/`). Incidents happen in the simulator; your agent
investigates them through tools, and the simulator reacts to what it does.

An agent is a model plus a **harness**: the instructions, the tools, the
format of the answer and the checks around it. In this session you keep the
model and build the harness:

- **Exercise 1:** give the agent the tools it needs to investigate.
- **Exercise 2:** let the agent fix the problem, and check in code that the fix worked before it can say "resolved".

Run every command from the repository root, after `uv sync` and after setting
`ANTHROPIC_API_KEY` in a local `.env` file. Commands are written on one line so
that they work in any terminal (PowerShell included).

## What you have

```text
01-agent-harness/
├── starter/harness.py   # the agent you start from
├── cases/               # the incidents of this session
└── checks/              # the success criteria of each incident (PASS / FAIL)
```

- **`starter/harness.py`** is a PydanticAI agent. It has three parts you can
  change: the instructions (`INSTRUCTIONS`), the format of the answer
  (`IncidentReport`) and the tools. Right now it has one tool:
  `read_alert`.
- **`cases/`**: one file per incident. Each file says what breaks in the
  simulator. The agent never reads these files; it only sees what its tools
  return.
- **`checks/`**: one file per incident with its success criteria. The runner
  reads them and prints PASS or FAIL.

The incidents:

| Case | What happens | Exercise |
|---|---|---|
| `s01-market-data-delay` | Market data arrives late. | 1 |
| `s01-metrics-unavailable` | The gateway is slow and the metrics service is down. | 1 |
| `s01-flaky-metrics` | The gateway is slow and the first metrics request fails. | 1 |
| `s01-gateway-latency` | The order gateway is slow. | 2 |
| `s01-stale-alert` | Everything is fine, but an old alert was left open. | 2 |
| `s01-alert-cleared-errors` | The latency alert closed by itself. Is the incident over? | 2 |

## The commands

Watch an incident in the simulator, without any agent:

```bash
uv run mrx-chaos run sessions/course-02-agentic-ai/01-agent-harness/cases/s01-gateway-latency.yaml --ticks 5 --component order-gateway
```

Run an agent on one incident and see everything it did (the trace):

```bash
uv run python -m meridian.run --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness.py --scenario sessions/course-02-agentic-ai/01-agent-harness/cases/s01-gateway-latency.yaml
```

Run an agent on every incident and see one line per incident with PASS or FAIL:

```bash
uv run python -m meridian.run --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness.py --cases-dir sessions/course-02-agentic-ai/01-agent-harness/cases --summary
```

- `--harness`: the agent file to run. Repeat it to compare two versions.
- `--scenario`: one incident. `--cases-dir`: every incident in a folder.
- `--summary`: only the table, without the traces.

A model does not always answer the same way. Run a case more than once before
drawing a conclusion.

## Exercise 1 — Give the agent the tools it needs

1. Run the starter on every incident (the `--summary` command above). Most
   cases fail.
2. Run it on `s01-gateway-latency` alone and read the trace. What did the
   agent use? What could it not find out?
3. Copy `starter/harness.py` to `starter/harness_v2.py`.
4. Add the tools the agent is missing. A tool is a Python function that
   calls the simulator through `ctx.deps.tools` (see `meridian/tools.py`).
   The simulator offers, among others:
   - `read_metrics(component, window_ticks, per_instance)`: recent metrics,
     optionally per instance;
   - `list_runbooks()` and `read_runbook(name, version)`: the procedures for
     each component.

   For every tool, decide: its name, its arguments, its docstring (that is
   what the model reads) and what it returns.
5. Run `harness_v2.py` on every incident.

**Done when** the three exercise 1 cases pass: `s01-market-data-delay`,
`s01-metrics-unavailable` and `s01-flaky-metrics`. The agent should also name
the instance with the problem in `s01-gateway-latency`, but that case only
passes after exercise 2.

**Write down:** which tools you added, why each one, and one decision about a
tool interface that changed what the agent did.

## Exercise 2 — Fix the problem, and check that it worked

So far the agent can only propose. Now it gets one action, and a check in
code that stops it from saying "resolved" unless the metrics confirm it.

1. Add a tool that restarts one instance. The simulator offers
   `ctx.deps.tools.restart_instance(instance_id)`. An instance is back after
   about 2 minutes. Restart only instances of non-critical components;
   repeated and unsafe actions are Session 2.
2. Run `s01-gateway-latency`. The agent should find `order-gateway-2`,
   restart it, and report "resolved".
3. Now add the check. The format of the answer is checked by PydanticAI, but
   nothing checks that the answer is true. Write a function that, when the
   report says `resolved`, reads the metrics itself and rejects the report if
   they do not confirm recovery. Use the recovery criterion of the runbook:
   latency below 20 ms and error rate below 1 % in the last 3 readings.

   PydanticAI runs this kind of check with an output validator: a function
   registered with `agent.output_validator(...)` that receives the report and
   either returns it (accepted) or raises `ModelRetry("reason")` (rejected:
   the report goes back to the model with the reason, and the model must
   answer again). Give the agent a few attempts: `Agent(..., retries=3)`.
4. Run every incident again. Look at:
   - `s01-alert-cleared-errors`: the latency alert closed, but errors are at
     6 %. A restart does not fix it. The check must stop "resolved".
   - `s01-stale-alert`: nothing is broken. The right answer is "resolved",
     without restarting anything.

**Done when** all six incidents pass.

**Write down:** why doing an action is not the same as fixing the problem,
and why a check in code is different from asking the model, in the
instructions, to "only report resolved with proof".

## Deliverable

- `starter/harness_v2.py`.
- A short note: the tools you added and why, the check you added and why, and
  what is still not demonstrated.
- One new incident in `cases/` with its file in `checks/` (copy an existing
  pair and change the fault, the component or the incident text). Run it.

## Conventions

- Keep a `status` field in the report. The checks read it.
- Do not edit `meridian/`. The simulator, the incidents and the runner are
  shared infrastructure.

## Scope boundary

One agent, a few tools, one simple action (restarting one instance of a
non-critical component), a typed answer and a check on the answer. Repeated
or unsafe actions, idempotency and choosing what goes into the context belong
to Session 2. MCP, memory, security policies and multi-agent coordination come
later in the course.
