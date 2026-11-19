# Self-Improving Incident Team

A design note for the project's main focus: a multi-agent incident team that improves itself, scored
by the workbench and traced with OpenTelemetry. All five build steps are built and run offline;
the build order is at the end, and the README has the commands.

## What Is Built

- The team runs as `project/team` from version files, with an offline stub model (`--model
  offline`), role checks and blame on its spans (`results review`).
- `app/case-splits.yaml` assigns every case to train, valid or test; `improve run` makes one
  candidate attempt for one role and decides on the train and valid sets; `improve test` runs the
  test set for a sealed team. Attempts are appended to `harnesses/versions/lineage.jsonl`.
- Lessons live in the memory store per role (`agent/lessons.py`). `run --memory` learns;
  `compare --memory-snapshot` and `improve run --memory-snapshot` give every run its own frozen
  copy and check the source is unchanged. The loop's copy drops lessons whose origin case is in
  the test split: a lesson's `source_ref` is `<run id>@<case id>`.
- `cases draft` turns a saved failing training run into a case and a check with a
  `coordination:` section; `run` appends those checks, judged on the team's handoffs, to the
  evaluation.

Simplifications:

- Role checks use end-of-run recovery state.
- A candidate is not yet scored alone on a sub-task before the team run; only the full team is
  compared.
- Lesson tools sit beside the version-file tools and are not part of a version, so a proposer
  cannot remove them. A failed run retires the lessons cited by a role whose own role check failed; no
  correction is written, so nothing is superseded yet.

## Starting Point

The section below is the state before the build.

- `harnesses/` is empty: the workbench can only run the read-only session harnesses.
- The session 6 lab has a working improvement loop (critic, proposer, keep-or-discard decision,
  attempt memory) in `sessions/course-02-agentic-ai/06-evaluation/lab/loop.py`, limited to the 10
  cases of sessions 1 and 2. Copies of its parts (`critic.py`, `suite.py`, `decision.py`,
  `pieces.py`, `models.py`) sit unused in `agent/`.
- `agent/team.py` (session 7) has four agents with typed handoffs (`NetworkFinding`,
  `RemediationReport`, `Review`, `Outcome`), run as a pipeline or by an orchestrator, but against the
  lab's own `world.py`, not the workbench.
- The workbench already scores any harness on all cases (`compare`), saves sets to `results/` and
  diffs them. `run_incident` takes a `memory_path`, so memory can persist across runs.
- Session 8 records OpenTelemetry spans with `gen_ai.*` attributes
  (`sessions/course-02-agentic-ai/08-agents-in-production/lab/record.py`).

## Three Ways to Improve

| Loop | What improves | Timescale |
| --- | --- | --- |
| Version loop | The team's design: instructions, tools, limits | Between versions |
| Lessons between incidents | What each agent knows | Between incidents |
| New cases from failures | The exam the team is scored on | Between loop runs |

```text
                                 ┌─────────────────────────────┐
                                 │ SELF-IMPROVING INCIDENT     │
                                 │ TEAM (Meridian project)     │
                                 └──────────────┬──────────────┘
          ┌─────────────────┬───────────────────┼───────────────────┬─────────────────┐
          ▼                 ▼                   ▼                   ▼                 ▼
   ┌─────────────┐   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   ┌─────────────┐
   │ FOUNDATIONS │   │ 1. VERSION  │     │ 2. LESSONS  │     │ 3. NEW CASES│   │ SAFEGUARDS  │
   │             │   │    LOOP     │     │   BETWEEN   │     │    FROM     │   │             │
   │             │   │             │     │  INCIDENTS  │     │  FAILURES   │   │             │
   └──────┬──────┘   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘   └──────┬──────┘
          │                 │                   │                   │                 │
 ├ team harness      ├ search space       ├ write after each   ├ mine failures    ├ no access to
 │  from version     │  instructions      │  incident: origin, │  from saved runs │  checks or
 │  files, all tools,│  tool subset       │  confidence,       ├ draft case +     │  evaluator
 │  right approver   │  limits            │  valid until, scope│  check           ├ test split
 ├ offline stub      │  verify recovery   ├ read before acting ├ cases validate   │  hidden until
 │  model (no cost)  ├ critic on spans    │  (scope, validity) ├ human review     │  the end
 ├ case splits       ├ proposer: one      ├ correct: pass      │  before write    ├ same initial
 │  train  s01-s04   │  change, remembers │  confirms, fail    └ training only    │  memory per
 │         + ½ ext   │  past attempts     │  supersedes                           │  comparison
 │  valid  s05-s09   ├ evaluate: compare  └ forget: expiry,                       ├ cost cap
 │  test   ½ ext     │  × repetitions        deletion log                         └ provisional
 ├ OTel spans        ├ decide: gain on train,                                        checks may
 └ cost cap          │  no regression on valid                                       be wrong
                     └ lineage: parent, change,
                        result set ids
```

The splits go by case family, and no `ext-` incident sits on both sides. The exact `ext-` halves
are still to be chosen.

### Version Loop

A proposer may change only version files (`harnesses/versions/`): instructions, the tools an agent
sees, request and tool limits, and whether recovery is verified before "resolved". It cannot touch
code, checks or the evaluator. Each candidate runs through `compare` on the training split with
repetitions; a decision rule keeps it only on a training gain with no validation regression. Every
kept version records its parent, its change and the ids of its saved result sets: that lineage is
the brief's "baseline and versions compared on the same cases and initial state".

### Lessons Between Incidents

After an incident an agent writes a lesson to the memory store (`meridian/memory.py`) with its
origin run, confidence, validity and scope. Later runs read lessons before acting. A lesson that a
later passing run used is confirmed; one behind a failing run is superseded. This is the "corrected
memories" evidence of the session 4 to 6 milestone.

### New Cases From Failures

An agent turns a failure pattern from saved runs into a draft case and check, validated with
`cases validate`. Nothing is written to `cases/` before human review, and new cases join the
training split only: a case the team wrote itself must never become its test.

### How the Loops Interact

```text
   ┌────────────────┐   memory frozen or reset    ┌────────────────┐
   │ 2. LESSONS     │ ──── per comparison ──────▶ │ 1. VERSION     │
   └────────────────┘   (else unfair baseline)    │    LOOP        │
           ▲                                      └───────┬────────┘
           │            ┌──────────────────┐              │ saved failures
           └────────────│ failure summary  │◀─────────────┘
                        │ (shared source)  │──────────────▶ 3. NEW CASES ──▶ training split only
                        └──────────────────┘
```

- Lessons that pile up during the version loop would give later candidates more memory than their
  baseline. Each comparison starts from a fresh or frozen memory snapshot.
- The critic and the case author read the same saved failures.

## Multi-Agent

The team (network, database, remediation, reviewer, plus an orchestrator) is wrapped so that
`build_agent(model)` returns the orchestrator, whose tools ask the specialists. The workbench then
runs, compares and saves the team like any harness.

```text
                         ┌──────────────────────────────────┐
                         │ TEAM VERSION = team.yaml         │
                         │  topology: orchestrator|pipeline │
                         │  orchestrator: v3                │
                         │  network: v5   database: v2      │
                         │  remediation: v4  reviewer: v1   │
                         └────────────────┬─────────────────┘
                                          │ run on workbench (compare)
                                          ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ TEAM TRACE: every tool call and every handoff tagged with its agent    │
   └───────────────┬──────────────────────────────┬─────────────────────────┘
                   │ case checks (meridian)       │ role checks (per agent)
                   ▼                              ▼
          team passed / failed           network found the cause?
                   │                     remediation acted on evidence?
                   │                     reviewer's verdict = real state?
                   └──────────────┬───────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │ BLAME (critic)            │
                    │ which agent or handoff    │
                    │ caused the failure?       │
                    └─────────────┬─────────────┘
          ┌───────────────────────┼────────────────────────────┐
          ▼                       ▼                            ▼
 ┌──────────────────┐  ┌─────────────────────┐      ┌─────────────────────┐
 │ 1. VERSION LOOP  │  │ 2. LESSONS          │      │ 3. NEW CASES        │
 │ change ONE agent │  │ scoped per role;    │      │ coordination        │
 │ (others frozen); │  │ shared lessons only │      │ failures: conflict- │
 │ test it alone on │  │ via the orchestrator│      │ ing findings, silent│
 │ its sub-task,    │  │ handover            │      │ specialist, lost    │
 │ then the team;   │  │                     │      │ handoff detail      │
 │ topology change  │  │                     │      │                     │
 │ = human gate     │  │                     │      │                     │
 └──────────────────┘  └─────────────────────┘      └─────────────────────┘

 FIXED, NEVER IN A VERSION FILE: permissions (who may act), handoff contracts
 (pydantic models), the reviewer's access to real state, the meridian checks
```

- **Blame first.** A team fails as a whole, but the proposer fixes one agent. Role checks score each
  agent: network named the broken component, remediation acted only after a supporting finding, the
  reviewer's verdict matches the simulator. The critic names the failing agent or handoff, which is
  also the brief's "failure between specialists detected" evidence.
- **One agent at a time.** A candidate specialist is first scored alone on its sub-task (cheap), and
  only then in the team. Topology changes (pipeline against orchestrator, adding or removing a
  specialist) need human approval.
- **Lessons per role.** The memory store's `team` field becomes the role scope. Network's lessons
  stay with network; team-wide lessons pass only through the orchestrator's handover.
- **The reviewer is never the objective.** If the loop could tune the reviewer, it could make it
  lenient and pass without fixing anything. The team is optimised on the meridian checks; the
  reviewer is scored on agreeing with the real state.

## Tracing and the Critic

The critic reads OpenTelemetry spans. Spans nest, so each agent's subtree, cost and blame come for
free, where `tools.trace` is a flat list with no agent attached.

```text
 workbench.run  {meridian.run_id, case_id, harness, model}  ← root span we add
 │  events: meridian.tool_call {step, tick, time, tool}, meridian.approval
 ├─ invoke_agent orchestrator
 │  ├─ execute_tool ask_network
 │  │  └─ invoke_agent network
 │  │     ├─ execute_tool check_link  {args, result}
 │  │     └─ execute_tool recent_changes
 │  ├─ execute_tool ask_remediation
 │  │  └─ invoke_agent remediation
 │  │     ├─ execute_tool request_approval
 │  │     └─ execute_tool rollback_change
 │  └─ execute_tool ask_reviewer → invoke_agent reviewer
 └─ meridian.evaluate  {checks_passed, checks_failed: names only}  ← span we add

        │ split by trace_id, masked, saved as results/<set>/<run>.spans.json
        ▼
 role checks (code) + per-agent view (code) + cost per agent (gen_ai.usage)
        ▼
 critic (LLM) → Blame(agent, span_id, problem, fix_hint) → proposer → decision
```

1. **Recording.** The runner enables `Agent.instrument_all` and wraps each run in a `workbench.run`
   root span. Instrumentation is global and runs execute in threads, so spans are grouped by
   `trace_id` under that root, not by thread.
2. **Simulator facts.** The runner adds what PydanticAI cannot know: a `meridian.tool_call`
   event per simulator tool call (step, simulated tick and time), a `meridian.approval` event per
   approval, and a `meridian.evaluate` span with each check's verdict. Check names and verdicts only:
   a check's detail (for example the expected change id) would hand the answer to the proposer.
3. **Code before the LLM.** Ordering, actions outside a role and cost per agent are computed from
   spans. The critic judges only what code cannot, such as whether a finding fits the evidence read.
4. **Blame points at a span.** A blame whose `span_id` does not exist, or lies outside the blamed
   agent's subtree, is rejected in code, like session 6's `evidence_is_real` check.

### Export

```text
   pydantic-ai gen_ai.* spans + workbench.run / meridian.* spans
                              ▼
   TracerProvider (service.name, service.version = team version, deployment.environment)
                              ▼
   MaskingExporter: masks personal data once, before any export
                ▼                                   ▼
   run collector (always on)              OTLP/HTTP exporter (Batch)
   results/<set>/<run_id>.spans.json      on when OTEL_EXPORTER_OTLP_ENDPOINT is set
   → critic, GUI, evidence                → Tempo, shown in Grafana
```

- **Standard variables only**: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_HEADERS`. Runs export whenever the endpoint is set, with no extra flag; with
  none set they still write the span file. Tests unset the endpoint.
- **OTLP over HTTP** via `opentelemetry-exporter-otlp-proto-http`, which must be added to
  `pyproject.toml` and the lock file. OTLP is vendor-neutral, so the backend stays a one-variable
  change.
- **Setup once, before the thread pool.** `app/core/telemetry.py` configures the provider in
  `run_matrix` and the single-run path, under a lock. Lazy setup in `run_case` would let two
  workers register processors twice, and a missing exporter would fail every run instead of
  startup.
- **Masking wraps the exporter.** A span processor sees spans after they end, when they can no
  longer change; the wrapper exports masked copies, so personal data leaves by neither path.
  `results/` is committed, which makes this a hard requirement. It masks every text field: the span
  name, the status description, string and string-list attributes, event attributes (a raised
  exception puts its message and stack trace there) and the resource. It masks first and caps
  length after, since a cut can leave half an address the patterns no longer match.
- **Content capture on**, with the format pinned
  (`InstrumentationSettings(include_content=True, version=6)`): the critic needs tool results, and
  masking makes it safe. The critic reads the compact view, never raw spans.
- **One trace per run.** `run_case` creates the `run_id`, opens `workbench.run`, runs, adds the
  effect events and the `meridian.evaluate` span, closes the root, drains the run's spans by
  `trace_id`, then writes the file. Four runs in parallel threads keep separate traces (checked
  with a stub model).
- **Session 8 format.** The span file has `title`, `source` and `spans`, and root attributes use
  the `meridian.` prefix, so session 8's `Trace` and its monitors read workbench runs unchanged.
- **Backend: Tempo and Grafana.** `telemetry/docker-compose.yml` runs both on 127.0.0.1; set
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318`. A workstation collector on `:4318` relays
  to a shared Tempo instead, once that backend accepts traces.
- **Cost on the trace.** PydanticAI prices each `chat` span (`operation.cost`, from
  `genai-prices`). Before the root closes, the runner writes the run's model calls, tokens and
  cost onto it and adds one `meridian.agent_usage` span per agent, so cost per agent is in the
  trace the critic reads, and the dashboard can group cost by harness, case, model and agent.
- **One span per summed series.** Tempo 3.0 returned one run's cost, not the total, when
  `sum_over_time` added several spans in one series (seen at most step sizes, not traced to an
  upstream issue). The dashboard sums only series grouped by run id and lets Grafana add them.
- The stub model emits spans too, so recording, role checks and blame validation test offline.

References:

- OTel SDK environment variables: <https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/>
- Python exporters: <https://opentelemetry.io/docs/languages/python/exporters/>
- GenAI semantic conventions: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- PydanticAI and OpenTelemetry: <https://ai.pydantic.dev/logfire/#using-opentelemetry>
- Tempo configuration: <https://grafana.com/docs/tempo/latest/configuration/>

## Cost

Live runs need approval before they start. Rough estimate, not measured: 20 cases × 3 repetitions
of the incident agent on `claude-haiku-5-5` stay under $0.50 per iteration; a team multiplies that
by its agent count, which is why specialists are scored alone first. Critic and proposer on
`claude-sonnet-5-5` add cents.

## Build Order

1. Record masked spans per run with file and OTLP export. Tracing lives in the runner, so it works
   on the session harnesses before the team exists.
2. Wrap the team as a workbench harness driven by version files, with the full tool set
   (`isolate_instance`, `failover`) and approval by role instead of a hard-coded "on-call"; add an
   offline stub model that works on every case. Then role checks and blame on its spans.
3. Version loop over a single agent, with splits, decision rule and lineage.
4. Lessons scoped per role.
5. New cases targeting coordination failures.

## Open Decisions

Decided defaults:

- The `ext-` halves of the training and test splits: see `app/case-splits.yaml`.
- The cost cap per live loop run: $5 (`--cap-usd`), and $0 offline.
