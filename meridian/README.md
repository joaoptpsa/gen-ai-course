# Meridian Exchange simulator

A small, state-based simulator of a fictional stock exchange, used by Course 2.
There is no real infrastructure: the simulator keeps a few numbers per
component and derives every metric, log line and alert from them. Agents never
read the state directly; they use the tools in `tools.py`, and the simulator
reacts to their actions.

`uv sync` installs it as the `meridian` package, so any session or project can
`import meridian`.

## Components

```text
 Members ──▶ order-gateway ──▶ matching-engine ◀── market-data
                  │                   │
                  ▼                   ▼
             reference-db ◀────── settlement
```

`matching-engine` and `reference-db` are critical: the executor rejects
actions on them without an approval. The topology lives in
`data/topology.yaml`.

## Modules

| Module | Role |
|---|---|
| `model.py` | Components, instances, links and changes (the state). |
| `rules.py` | What happens on every tick: resource pressure, cut links, error rates, queues, latency. |
| `faults.py` | Five fault mechanisms: `link`, `resource`, `change`, `data`, `noise`. |
| `actions.py` | Restart, rollback, isolation, failover and the executor (audit log, idempotency keys, approvals, lost responses). |
| `signals.py` | Metrics, logs, alerts and tickets generated from the state. |
| `clock.py` | Simulated time and the trading session. |
| `tools.py` | The tools agents can use. Every call is traced and moves time forward. |
| `scenarios.py` | Scenario and solution files. |
| `evaluate.py` | Checks a run against a solution file. |
| `agent_runtime.py`, `run.py` | Load a harness, run it on a scenario, print the trace. |
| `cli.py` | `mrx-chaos`: watch a scenario without an agent. |
| `mcp_servers/` | Simulated MCP servers: tickets (Jira-like), monitoring (LogicMonitor-like), deployments. Session 3 onwards. |
| `memory.py` | Persistent memory store (SQLite) with origin, confidence, validity, teams, corrections and deletions. Session 4 onwards. |
| `security.py` | Facts about an action for a security policy (role, critical target, trading session, approval). Session 5 onwards. |
| `data/identities.yaml` | Test identities: first-line agent, on-call engineer, incident manager, another team. |

## Time

One tick is one simulated minute. Time only moves when the agent calls a tool
(`ticks_per_action`, one by default), never while the model is thinking. A
slower model therefore faces exactly the same state as a faster one, and the
same scenario with the same seed always produces the same signals.

## Scenario files

A scenario describes what happens. It never contains the expected answer.

```yaml
id: s01-example
title: Short description
seed: 11
start_time: "10:05"          # time when the agent starts
warmup_ticks: 15             # ticks simulated before the agent starts
ticks_per_action: 1
background_log_lines: 3      # random healthy log lines per tick
incident:
  id: INC-0001
  summary: "Text the agent receives."
  alert: latency_high/order-gateway
changes:                      # changes that happen during the scenario
  - {change_id: CHG-1, component: reference-db, kind: config, description: "...", at: 5}
faults:
  - {type: resource, at: 2, instance: order-gateway-2, resource: memory, start_value: 88, rate: 0.3}
  - {type: link, at: 3, source: order-gateway, target: reference-db, mode: down}
  - {type: change, at: 5, change_id: CHG-1, effects: [{component: order-gateway, error_rate: 0.3, reason: "..."}]}
  - {type: data, at: 4, component: market-data, delay_ms: 400}
  - {type: noise, at: 6, noise: duplicate_alerts, component: order-gateway, rule: latency_high, count: 50}
logs:                         # exact log lines injected at a tick
  - {at: 5, component: reference-db, level: WARN, message: "..."}
alerts:                       # alerts injected at a tick (auto_resolve: false keeps them open)
  - {at: 1, rule: latency_high, component: order-gateway, auto_resolve: false}
tools:                        # tool behaviour
  read_metrics: {fail_calls: [1]}        # or {unavailable: true}
executor:
  drop_response:                          # apply the action, but lose the answer
    - {action: restart_instance, call: 1}
approvals: []                             # approval references accepted for critical components
```

Later sessions add optional sections:

```yaml
date: "2026-11-04"                    # simulated date (memories and changes have dates)
tickets:                              # tickets present or arriving during the incident
  - {at: 12, key: MRX-2210, project: MRX, issue_type: Incident, summary: "...", description: "...", component: order-gateway}
mcp:                                  # Session 3: how the MCP servers look in this scenario
  servers:
    monitoring: {version: "3.0.0", publisher: observability-team, descriptions: {get_device_datapoints: "..."}}
  credentials:
    tickets: {scopes: [tickets:read]}
memory_seed:                          # Session 4: memories written in earlier shifts
  - {memory_id: MEM-0001, kind: known_issue, subject: order-gateway, content: "...", source_type: user,
     source_ref: rita.alves, author: rita.alves, team: trading-ops, created_at: "2026-10-14 09:40", confidence: 0.9}
actor: {role: on-call}                # Session 5: identity the agent acts as
approver: {mode: approve_all}         # simulated human approver: {mode: approve_all}, {mode: deny_all} or {approve_roles: [...]}
```

Cases adapted from public postmortems use these optional fields:

```yaml
sites:                                # what `failover <component>:<site>` can reach
  order-gateway:
    primary: A
    standby:
      B: {error_rate: 0.9, reason: "site B in maintenance"}   # reachable, but unhealthy
      C: {}                                                   # healthy
      D: {fails: true, reason: "switchover flaw"}            # the move is refused
faults:
  - {type: link, at: 3, site: A, source: order-gateway, target: reference-db, mode: degraded, extra_latency_ms: 200}
  - {type: change, at: 1, effects: [{component: order-gateway, instance: order-gateway-2, error_rate: 0.8}]}
  - {type: change, at: 1, change_id: CHG-1, trigger: rolled_back, effects: [...]}   # starts when CHG-1 is rolled back
  - {type: change, at: 1, change_id: CHG-2, sticky: true, effects: [...]}           # stays on each instance until it restarts
```

`site` makes a fault apply only while its component runs on that site. A
failover restarts the component's instances on the new site, so it is down for
two ticks; isolated instances stay isolated. `isolate_instance` takes an
instance out of service; `restart_instance` brings it back.

## Solutions

Solutions (root cause, recovery conditions, forbidden actions) are kept
outside the public repository, in the trainer's private folder, and are never
given to agents. When present, `python -m meridian.run` evaluates each run.
The format is documented at the top of `evaluate.py`. Set
`MERIDIAN_SOLUTIONS` to use another folder.

## Commands

```bash
uv run mrx-chaos show <scenario.yaml>
uv run mrx-chaos run <scenario.yaml> --ticks 20 --component order-gateway
uv run python -m meridian.run --harness <harness.py> --scenario <scenario.yaml>
uv run python -m meridian.mcp_servers inspect [--scenario <scenario.yaml>]
uv run python -m pytest meridian/tests
```
