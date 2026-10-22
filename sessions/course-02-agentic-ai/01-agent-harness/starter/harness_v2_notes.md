# Session 1 Notes: `harness_v2.py`

`starter/harness_v2.py` covers exercises 1 and 2. The agent investigates with eight read tools,
restarts one instance when the runbook calls for it, and an output validator rejects "resolved"
unless the metrics confirm recovery. Every run used `claude-haiku-5-5`.

## Tools I Added and Why

| Tool | Why |
| --- | --- |
| `read_metrics` | Step 1 of both runbooks. Always per instance, so the agent can name the instance at fault. Retries once in code when the result says `retryable: true`. |
| `list_runbooks` | The only way the model learns the runbook names. A guessed name returns an error. |
| `read_runbook` | No `version` argument, so it returns the latest version. v1 says to restart the whole gateway, which `s01-gateway-latency` forbids. |
| `check_link` | Step 2 of the gateway runbook. The docstring lists which component depends on which. |
| `recent_changes` | Step 2 of `market-data-delays`. Adds the current date and `minutes_ago` to each change. |
| `list_alerts`, `read_logs` | The only evidence left when metrics are down (`s01-metrics-unavailable`). `read_logs` returns at most 30 lines. |
| `restart_instance` | The one action (exercise 2). Only `instance_id` is exposed. The executor already rejects critical components. |

I also added `affected_instance` and `actions_taken` to the report.

## One Interface Decision That Changed What the Agent Did

Alerts and metrics show only the time of day. In `s01-market-data-delay`, deploy `CHG-4302` ran at
13:05 two days before the delay started at 13:07, so the first agent took it as the cause and
proposed a rollback. `recent_changes` now returns `now` (date and time) and `minutes_ago` per change.
In the next three runs the agent saw the deploy was about 2900 minutes old and advised against a
rollback.

## The Check I Added and Why

`check_recovery` is registered with `agent.output_validator(...)` and the agent has `retries=3`.
When the report says `resolved`, it:

1. Reads the incident's alert to find the component, so the model does not choose what is checked.
2. Reads the last 3 metric readings of that component through `ctx.deps.tools`.
3. Keeps only readings taken after the latest restart (the runbook asks for readings "taken after
   the action").
4. Raises `ModelRetry` with the reason unless there are 3 such readings and each meets the runbook's
   criterion: `order-gateway` latency below 20 ms and errors below 1 %, `market-data` latency below
   10 ms.

It also rejects "resolved" when the metrics cannot be read or the component has no known criterion.
I called it directly on 10 simulator states, without a model. It accepted the 3 that should pass (a
healthy gateway, a gateway recovered after a restart, and a report that is not "resolved") and
rejected the other 7.

## Why an Action Is Not a Fix

A completed restart means the executor ran it, not that the symptom is gone. In
`s01-alert-cleared-errors` the latency alert closed by itself, but config change `CHG-4480` keeps
errors at 6 %, so a restart leaves them at 6 %. Only metrics read after the action show whether the
incident is over.

## Why a Check in Code Is Not the Same as an Instruction

An instruction is a request the model weighs against everything else in its context. The validator
runs on every report and reads the metrics itself. The new case shows the difference: the
instructions say to restart only when the runbook calls for it, and in 1 of 5 runs the agent
restarted an instance while runbook step 2 forbade it. That rule lives only in the instructions.
The recovery rule lives in code, so a false "resolved" cannot reach the report whatever the model
concludes.

## New Case: `s01-gateway-degraded-link`

`cases/s01-gateway-degraded-link.yaml` copies `s01-gateway-latency` and adds a degraded
`order-gateway -> reference-db` link (120 ms extra). `order-gateway-2` still leaks memory above
90 %, but step 2 of the v2 runbook says not to restart the gateway while a link is degraded.
`checks/s01-gateway-degraded-link.yaml` requires reading the link, mentioning `reference-db`, no
restart and no recovery claim.

## Results

| Case | Runs | PASS |
| --- | --- | --- |
| `s01-market-data-delay` | 2 | 2 |
| `s01-metrics-unavailable` | 2 | 2 |
| `s01-flaky-metrics` | 2 | 2 |
| `s01-gateway-latency` | 2 | 2 |
| `s01-stale-alert` | 2 | 2 |
| `s01-alert-cleared-errors` | 2 | 2 |
| `s01-gateway-degraded-link` | 5 | 4 |

The starter passed 1 of the 6 original cases (`s01-metrics-unavailable`, because it never claims
recovery).

## What Is Still Not Demonstrated

- Runbook step 2 is enforced only by the instructions: the agent restarted while a link was degraded
  in 1 of 5 runs.
- Nothing in code stops a second restart of the same instance, or a restart without metrics.
  `s01-metrics-unavailable` passes because the model chose not to act. Repeated and unsafe actions
  are Session 2.
- In the live runs the validator never had to reject a report: the model reported `unresolved` on
  its own in `s01-alert-cleared-errors`. Its rejections were shown only by calling it directly.
- The validator's metric reads go into the trace, so they count toward `required_reads` even when
  the model never read the metrics itself.
- The recovery criteria are copied by hand from the runbooks, and only for `order-gateway` and
  `market-data`.
- The restart treats the symptom: the memory growth behind `CHG-4310` continues, and the checks
  only look 5 minutes ahead.
- The checks do not grade the diagnosis: the market-data run that proposed a wrong rollback passed.
- Two to five runs per case are too few to give pass rates.
