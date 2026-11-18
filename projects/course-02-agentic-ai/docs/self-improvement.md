# Self-Improving Incident Team

A design note for the project's main focus: a multi-agent incident team that improves itself, scored
by the workbench and traced with OpenTelemetry. Nothing here is built yet; the build order is at the
end.

## Starting Point

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
 workbench.run  {run_id, case_id, team_version}            ← root span we add
 └─ invoke_agent orchestrator
    ├─ execute_tool ask_network
    │  └─ invoke_agent network
    │     ├─ execute_tool check_link  {args, result}
    │     └─ execute_tool recent_changes
    ├─ execute_tool ask_remediation
    │  └─ invoke_agent remediation
    │     ├─ execute_tool request_approval
    │     └─ execute_tool rollback_change   + event meridian.effect
    └─ execute_tool ask_reviewer → invoke_agent reviewer
 meridian.evaluate  {check: passed/failed, names only}     ← span we add

        │ split by trace_id, masked, saved as results/<set>/<run>.spans.json
        ▼
 role checks (code) + per-agent view (code) + cost per agent (gen_ai.usage)
        ▼
 critic (LLM) → Blame(agent, span_id, problem, fix_hint) → proposer → decision
```

1. **Recording.** The runner enables `Agent.instrument_all` and wraps each run in a `workbench.run`
   root span. Instrumentation is global and runs execute in threads, so spans are grouped by
   `trace_id` under that root, not by thread.
2. **Simulator facts.** The runner adds what PydanticAI cannot know: `meridian.effect` and approval
   events, and a `meridian.evaluate` span with each check's verdict. Check names and verdicts only:
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
   file exporter (always on)              OTLP/HTTP exporter (Batch)
   results/*.spans.json                   on when OTEL_EXPORTER_OTLP_ENDPOINT is set
   → critic, GUI, evidence                → Jaeger, Phoenix, Langfuse or a vendor
```

- **Standard variables only**: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_HEADERS` (a backend token lives in `.env`; `.env.example` gets placeholders).
  With none set, runs still write the local span file.
- **OTLP over HTTP** via `opentelemetry-exporter-otlp-proto-http`, the one new dependency. OTLP is
  vendor-neutral, so the backend stays a one-variable change.
- **Masking wraps the exporter.** A span processor sees spans after they end, when they can no
  longer change; the wrapper exports masked copies, so personal data leaves by neither path.
  `results/` is committed, which makes this a hard requirement.
- **Content capture on** (`InstrumentationSettings(include_content=True)`): the critic needs tool
  results, and masking makes it safe. The critic reads the compact view, never raw spans.
- **Local backend** from a container image (Jaeger all-in-one on `:4318`, or Phoenix), started by a
  `bin/` script, not installed on the host.
- The stub model emits spans too, so recording, role checks and blame validation test offline.

References:

- OTel SDK environment variables: <https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/>
- Python exporters: <https://opentelemetry.io/docs/languages/python/exporters/>
- GenAI semantic conventions: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- PydanticAI and OpenTelemetry: <https://ai.pydantic.dev/logfire/#using-opentelemetry>

## Cost

Live runs need approval before they start. Rough estimate, not measured: 20 cases × 3 repetitions
of the incident agent on `claude-haiku-5-5` stay under $0.50 per iteration; a team multiplies that
by its agent count, which is why specialists are scored alone first. Critic and proposer on
`claude-sonnet-5-5` add cents.

## Build Order

1. Wrap the team as a workbench harness driven by version files, with the full tool set
   (`isolate_instance`, `failover`) and approval by role instead of a hard-coded "on-call"; add an
   offline stub model that works on every case.
2. Record masked spans per run with file and OTLP export, then role checks and blame on top.
3. Version loop over a single agent, with splits, decision rule and lineage.
4. Lessons scoped per role.
5. New cases targeting coordination failures.

## Open Decisions

- Which OTLP backend: Jaeger, Phoenix, Langfuse or a vendor.
- Whether runs export whenever the endpoint is set, or only with an `--export` flag.
- The exact `ext-` halves for the training and test splits.
- The cost cap per loop run.
