# Exercise 1 Rationale

Why `starter/context_user.py` is built the way it is. Each section names a change, what it replaces and
the evidence that led to it.

## The Cost Model

Every model request resends the whole conversation: the first message, every earlier tool call and
every earlier result. The input tokens of a run are therefore the sum, over all requests, of
everything said so far. Two levers follow:

- Make the first message small, because it is paid for once per request.
- Make each tool result small and the number of requests low, because every result is paid for once
  per later request.

The starter spent 1,356,052 input tokens on `s02-noisy-gateway` over 6 requests, about 226k per
request. The budget is 40,000.

## Context Policy

| Bucket | What goes there |
| --- | --- |
| Always in the prompt | The incident line and a pointer to the tools |
| Loaded on demand, by tool | Metrics, alerts and log summaries, the runbook of the running version, changes |
| Never loaded | Raw log lines, every runbook, duplicated alerts |

Anything taken out of the prompt is reachable with a tool.

## Changes

### `build_prompt`: Incident Line Plus a Pointer

The dumps of alerts, logs and runbooks were the whole 226k. Replacing them with one sentence moved
the run from 1,356,052 to 406,796 tokens, still over budget because the agent then fetched raw
logs with `read_logs`.

### `template_of` and `summarize_logs`

- Logs come from a few dozen templates and only the values change. Replacing ids such as
  `CHG-4471`, IP addresses, `key=value` values and remaining numbers, in that order, collapses about
  1,000 lines per component into 2 to 6 templates.
- Frequency alone hides the cause. The line that explains thousands of errors appears once, for
  example `max_connections changed from 500 to 60 (CHG-4471)`. A template is rare when it was seen
  once or twice, or first seen in the last 30 minutes. A symptom that started with the fault is
  recent, so it also surfaces.
- Rare templates come first, rarest first, each with its count, first and last time, instances and
  one full example with its log ref, so the agent can cite it.
- Common templates are counts only. A summary stays near 600 characters.
- `read_logs` is removed from `TOOLS`. One call returns every line and every later request would
  resend them.

### `open_alerts` Inside `summarize_logs`

Alerts are grouped by rule and instance, rarest first. 200 duplicates become one line, and an alert
on a single instance such as `memory_pressure order-gateway-2` says where to look. They live in
`summarize_logs` and not in the prompt because they are signals about a component, like its logs,
and the prompt stays minimal.

### `find_runbook`

It reads the running version from the latest metrics reading and picks the runbook whose
`applies_to` matches, turning `2.4.x` into `2.4.*` for `fnmatch`. This prevents following the
runbook of the 2.3.x gateway, which restarts the whole service.

### `read_metrics`: Compact and Capped at 5 Ticks

The model asked for 15 ticks per instance on every component, about 2k tokens a call. The result
now drops fields that are constant or rarely matter, moves `version` to the top level and puts each
instance on one line. A 5-tick per-instance read went from 2,016 to 1,382 characters. The window is
capped at 5 and the docstring says so.

### `wait_for_recovery`

After an action the agent has to wait for the runbook's recovery criterion, for example latency
under 20 ms for 3 consecutive readings. Polling with `read_metrics` costs one request per minute,
and each request resends a 7k to 13k context. In `s02-firewall-change` the investigation took
about 5k tokens and polling took the rest, 106k tokens at its worst.

The tool polls once a minute inside one call, until the criterion holds for the required
consecutive readings or `max_minutes` passes, and returns only the final state. A real agent would
wait the same way, with a sleep between polls.

### `INSTRUCTIONS`

- A look order from the exercise hint: metrics, runbook, logs of the alerting component.
- Act when metrics and logs already explain the incident. Check dependencies and changes only when
  they do not. Without this the agent summarized the logs of every dependency, 4 extra calls in
  `s02-noisy-gateway`.
- Roll back when the cause is a change. Without it the agent stopped at "probable cause" in
  `s02-firewall-change`.
- After acting, call `wait_for_recovery` with the runbook's criterion.

### `Args:` Docstrings

Each tool has a one-line summary and an `Args:` section, as in
`01-agent-harness/starter/harness_v2.py`. PydanticAI turns each argument description into the tool's parameter schema, so the model reads it
with the tool. The first line stays a stand-alone summary, because the catalog shows only that line.

## Tried and Removed

- **Batching the same read to pass time.** Telling the agent to issue several `read_metrics` calls
  in one step to wait for recovery lowered the totals, but only because the simulator advances the
  clock on every tool call (`meridian/tools.py`, `meridian/simulator.py`). In a real system
  concurrent reads of one metric return about the same instant and wait for nothing. It exploited
  the simulator, so it was replaced by `wait_for_recovery`.
- **A component list in the prompt.** Added to stop the agent guessing names such as `database`.
  The `Args:` docstrings already list the names, and the guessing did not return without it.
- **An alert digest in the prompt.** It cost tokens on every request. It moved into
  `summarize_logs`.
- **"Critical components cannot be changed by you" in `INSTRUCTIONS`.** The agent read it as a
  reason not to roll back. The executor already refuses changes to critical components.

## Where the First Policy Dropped What the Agent Needed

The first `build_prompt` kept only the incident line. The alert and log dumps it replaced also
carried every component name, and nothing else in that version gave the names. In
`s02-hidden-config-change` the agent then guessed a component called `database`:

| Call | Result |
| --- | --- |
| `read_metrics(component="database")` | `Unknown component: database` |
| `summarize_logs(component="database")` | `total_lines: 0` |
| `summarize_logs(component="order-gateway-1")` | `total_lines: 0` |

It still found `CHG-4471` on `reference-db`, but only as "Probable", and the wasted requests took
the run to 50,507 tokens, a FAIL on the budget. A component list in the prompt stopped the
guessing. It was removed later, because the `Args:` docstrings list the names and the guessing did
not come back (see Tried and Removed).

This comes from the session transcript of 2026-10-27, not from git. Git holds only the final
version of each commit.

## Measured Results

Three full runs of the four cases with the final `context_user.py`, input tokens per run:

| Case | Run 1 | Run 2 | Run 3 | Result |
| --- | --- | --- | --- | --- |
| `s02-noisy-gateway` | 25,452 | 26,949 | 26,923 | PASS |
| `s02-firewall-change` | 28,440 | 28,568 | 27,154 | PASS |
| `s02-hidden-config-change` | 28,349 | 28,409 | 35,684 | PASS |
| `s02-lost-response` | 35,134 | 30,883 | 36,270 | PASS |

All 12 runs passed, the highest at 36,270 tokens against the 40,000 budget. Token counts vary
between runs, because the model chooses its calls.

## New Case: `s02-feed-scale-change`

The gateway rejects a quarter of its orders with HTTP 503. The cause is one line in the
`market-data` logs, two hops away: the gateway depends on `matching-engine`, which depends on
`market-data`.

| Where | What the agent sees |
| --- | --- |
| `order-gateway` logs | `reason=matching-engine rejected order: price outside band`, 21 lines, plus one rare `config reloaded: session_timeout_s 30 -> 45 (CHG-4507)` at 14:42 |
| `matching-engine` logs | `price band check failed: last price off by 100x`, 22 lines |
| `market-data` logs | One line at 14:45: `publisher reloaded: price_scale 4 -> 2 for all symbols (CHG-4512); consumers still decode with scale 4` |
| `market-data` metrics | Healthy: 3 ms latency, 0.1% errors, no alert |
| `recent_changes` | `CHG-4512` "Refresh market-data publisher settings" and `CHG-4507` "Tune order-gateway session timeouts" |

The check expects a rollback of `CHG-4512`, no rollback of `CHG-4507`, no restart, a report that
names `CHG-4512` and claims recovery, and gateway and matching-engine error rates under 1% for 5
ticks.

How it differs from the other two cases with the cause elsewhere:

| Case | Line is in | Hops from the alert | Fix |
| --- | --- | --- | --- |
| `s02-hidden-config-change` | `reference-db`, critical | 1 | None, report only |
| `s02-firewall-change` | `order-gateway` itself | 0 | Roll back |
| `s02-feed-scale-change` | `market-data`, not critical | 2 | Roll back, and skip a decoy |

The naive approach misses it in three ways:

- Reading only the alerting component's rare lines finds `CHG-4507`. It is a change on the gateway,
  3 minutes before the errors, and rolling it back fixes nothing.
- Checking only direct dependencies stops at `matching-engine`, which is critical and only shows the
  symptom.
- Metrics point nowhere: `market-data` looks healthy. Only its logs explain the errors, and only
  the log line ties the bland description of `CHG-4512` to the price errors.

### Runs

Five runs with `harness_user.py`, which loads all three `_user` files:

| Run | Requests | Input tokens | Tool calls | Result |
| --- | --- | --- | --- | --- |
| 1 | 6 | 36,246 | 12 | PASS |
| 2 | 6 | 35,362 | 11 | PASS |
| 3 | 7 | 41,301 | 13 | FAIL, budget only |
| 4 | 6 | 33,942 | 11 | PASS |
| 5 | 7 | 45,546 | 14 | FAIL, budget only |

In all 5 runs the agent followed gateway, matching-engine, market-data, cited the
`market-data` line, rolled back `CHG-4512` once and left `CHG-4507` alone. Every other check
passed.

Both failures made a 7th request. In each, the agent called `search_tools` for a rollback tool
before rolling back. From the trace, the router had not offered `rollback_change` at the start. In
the passing runs it rolled back without searching. That is exercise 2's router, not this file.

I left `context_user.py` unchanged. Every tool result of a run adds up to about 6,600 characters,
roughly 2k tokens: metrics 1,362, runbook 733, the three log summaries 1,056, 711 and 586, changes
784, metrics again 1,338. The rest of the 34k to 46k is resent on every request: instructions,
tool definitions and the conversation. So the cost follows the number of requests, and a smaller
summary would barely move it.

## Open

- `s02-feed-scale-change` passes in 3 of 5 runs. The failures come from the router missing
  `rollback_change`, which belongs to exercise 2.
