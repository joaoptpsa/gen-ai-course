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
| `recent_changes` | Step 2 of `market-data-delays`. Adds `as_of` (the date and time of the answer) and `minutes_ago` to each change. |
| `list_alerts`, `read_logs` | The only evidence left when metrics are down (`s01-metrics-unavailable`). `read_logs` returns at most 30 lines. |
| `restart_instance` | The one action (exercise 2). Only `instance_id` is exposed. The executor already rejects critical components. |

I also added `affected_instance` and `actions_taken` to the report.

## One Interface Decision That Changed What the Agent Did

Alerts and metrics show only the time of day. In `s01-market-data-delay`, deploy `CHG-4302` ran at
13:05 two days before the delay started at 13:07, so the first agent took it as the cause and
proposed a rollback. With `minutes_ago` alone, the agent called the age inconsistent with the 13:05
timestamp and still proposed it. Adding the date fixed most runs: `recent_changes` returns `as_of`
(the date and time of the answer) and `minutes_ago` per change. In 2 of the last 10 market-data runs
the agent still doubted or misread the date.

The field was first called `now`. Every later tool call moves the clock a minute, so it fell behind,
and one agent compared it with later metric readings and suspected the metrics clock (1 of 41
runs). After renaming it to `as_of`, no run mentioned the clock (0 of 10).

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
runs on every report and reads the metrics itself, whatever the model concluded. In 51 live runs,
6 of them with the "resolved" rule removed from the instructions, the model never claimed a false
"resolved", so the validator never had to reject a report. With this model the instructions were
enough; the check keeps holding for another model, prompt or incident where they are not.

The validator guards one direction only. The live failures went the other way: the agent reported
`unresolved` on a healthy system (`s01-stale-alert`, 1 of 10 runs, because the old alert was still
open) and, without the "resolved" rule, after a restart that had worked (`s01-gateway-latency`, 1
of 3). Nothing in code catches an agent that is too cautious.

## New Case: `s01-gateway-degraded-link`

`cases/s01-gateway-degraded-link.yaml` copies `s01-gateway-latency` and adds a degraded
`order-gateway -> reference-db` link (120 ms extra). `order-gateway-2` still leaks memory above
90 %, but step 2 of the v2 runbook says to investigate the dependency and its recent changes before
restarting the gateway. A restart of `order-gateway-2` lowers latency from 269 ms to 125 ms, and the
link keeps it there.

`checks/s01-gateway-degraded-link.yaml` requires reading the link and the recent changes of
`reference-db`, mentioning `reference-db`, and no recovery claim. It allows one restart of
`order-gateway-2` and none of `order-gateway-1` or the service. In 5 runs the agent investigated
`reference-db` every time, restarted `order-gateway-2` in 2 and escalated without a restart in 3.

## Results

With the checks as committed. `s01-market-data-delay` and `s01-stale-alert` ran 5 more times after
the `as_of` rename, the field they depend on:

| Case | Runs | PASS |
| --- | --- | --- |
| `s01-market-data-delay` | 10 | 10 |
| `s01-metrics-unavailable` | 5 | 5 |
| `s01-flaky-metrics` | 5 | 5 |
| `s01-gateway-latency` | 5 | 5 |
| `s01-stale-alert` | 10 | 9 |
| `s01-alert-cleared-errors` | 5 | 5 |
| `s01-gateway-degraded-link` | 5 | 5 |

The starter passed 1 of the 6 original cases in one run (`s01-metrics-unavailable`, because it
never claims recovery).

## What Is Still Not Demonstrated

- The validator has not rejected a report in a live run (0 in 51).
- An agent that reports `unresolved` on a recovered system is not caught: `s01-stale-alert` failed 1
  of 10 runs this way.
- The order of runbook steps is not checked: the evaluator cannot tell whether the agent
  investigated `reference-db` before or after restarting.
- Nothing in code stops a second restart of the same instance, or a restart without metrics.
  `s01-metrics-unavailable` passes because the model chose not to act. Repeated and unsafe actions
  are Session 2.
- The validator's metric reads go into the trace, so they count toward `required_reads` even when
  the model never read the metrics itself.
- The recovery criteria are copied by hand from the runbooks, and only for `order-gateway` and
  `market-data`.
- The restart treats the symptom: the memory growth behind `CHG-4310` continues, and the checks
  only look 5 minutes ahead.
- The checks do not grade the diagnosis: market-data runs that proposed a wrong rollback passed.
- Five to ten runs per case is still a small sample.
