# Exercise 2 Rationale

Why `starter/tool_selection.py` is built the way it is, what the experiments showed and where it
falls short.

## Status

`check_routing.py` is not reliably met. In the last three runs coverage was 0.94, 0.94 and 0.96
against the target of 0.95, with 9.7 tools on average (target 10 or fewer) and no never-offered
tool. The four cases passed in 11 of 12 runs. The router is a model, so coverage moves about ±0.03
between runs.

## Design

| Part | What it does |
| --- | --- |
| `select_tools` | A model chooses from one summary line per tool. Code corrects the choice. |
| `correct_selection` | Adds the core, drops unknown and never-offered names, removes duplicates, caps at 10. |
| `CORE_TOOLS` | `read_metrics`, `summarize_logs`, `find_runbook`, `recent_changes`: where every investigation starts. |
| `waiting_for` | Adds `wait_for_recovery` whenever an action tool is selected, because waiting follows acting. |
| `search_tools` | Scores catalog tools by words shared with the agent's described need and adds the best 3. |
| `NEVER_OFFERED` | `read_logs_v1`, `get_metrics_legacy`, `restart_all`: removed by exact name in the router prompt, in `correct_selection` and in `search_tools`. |
| Fallback | If the model call fails, a warning is logged and the core is used. |

The model decides which tools an incident needs. Code decides what is never allowed, what is always
present and how many. The router is not the limit: `search_tools` can add tools during the run, up
to `MAX_TOOLS + 2 * SEARCH_RESULTS`.

## Why the Router Sees the Core

The router prompt lists the core tools under "Already given", and excludes them and the
never-offered tools from the choices. Without that the model spent slots on tools that duplicate the
core, such as `read_logs` next to `summarize_logs`. Showing the core also lets it see what is
covered. The setting `temperature=0` was tried and removed: `claude-haiku-5-5` ignores it and the library
warns.

## Why `list_alerts` Is Overridden

The platform's `list_alerts` returns up to 50 raw alerts, about 11.7k characters. On
`s02-noisy-gateway` there are 202 open alerts and 201 are the same duplicate. Runs where the agent
called it cost about 55k tokens, and runs where it did not cost about 31k, because the result is
resent in every later request. `context.py` now overrides it by name with the grouped digest that
`summarize_logs` already returns, and the case stays near 30k.

## Why the Critical-Component Rule

A rollback of `CHG-4471` on `reference-db` is always rejected, because it is a critical component.
The agent then searched for an approval tool, asked for approval and retried the rollback, which
took 8 requests and 39k to 51k tokens. `INSTRUCTIONS` now says a change on `reference-db` or
`matching-engine` is reported as the root cause instead of rolled back, and the case costs about
12.6k tokens in 3 of 3 runs. The case's own check says the agent "cannot fix it, only find it".

## Why `search_tools` Is Needed

On `s02-noisy-gateway` the incident line names no instance, so the router does not offer
`restart_instance`. The agent finds it with `search_tools`, and `wait_for_recovery` arrives with it.
That is the router being wrong at the start and the safety net recovering.

## Experiments on the Router

Each variant ran 3 times per set, scoring coverage and the router's own tokens per incident, which
the 40,000-token budget does not count. Mean coverage:

| Variant | 20 incidents | Holdout | Router tokens | Calls |
| --- | --- | --- | --- | --- |
| Current (one call) | 0.92 | 0.97 | ~2,230 | 1 |
| Plan field before the tool list | 0.89 | 0.85 | ~2,270 | 1 |
| Second call that audits the picks | 0.90 | 0.85 | ~4,440 | 2 |
| Plan field plus signals | 0.91 | 0.90 | ~2,320 | 1 |
| Code signals on the current router | 0.93 | 0.92 | ~2,200 | 1 |

No variant beat the current router beyond the run-to-run noise. A second audit call doubles the
router cost and scores no better, and that cost does not show in the budget, so it was not kept.
The signals were ids only: an instance id adds `read_instance_metrics`, `ALR-n` adds `read_alert`, a
ticket key adds `read_ticket` and `CHG-n` adds the rollback tool.

The holdout sets were written after reading the 20 incidents, so they are weak evidence.

## Tried and Reverted: Tuning the Prompt to the Incidents

The same five tools were missed in nearly every run: `action_status`, `comment_ticket`,
`trading_calendar`, `check_link` and `read_ticket`. A rewritten "Consider" list naming a situation
for each raised coverage on the 20 incidents to 0.96 to 0.99. On two holdout sets it did not move.
That is tuning to the incidents, which the exercise warns against, because the situations were
written after seeing which tools were missed on those incidents. It was reverted, and the earlier
list stays. That earlier list also came after seeing misses, so even the 0.94 is partly tuned.

## Measured Results

With the final code:

| Check | Result |
| --- | --- |
| `check_routing.py`, 3 runs | coverage 0.94, 0.94, 0.96; size 9.7; never-offered 0 |
| `s02-noisy-gateway`, 3 runs | 28,257 / 30,126 / 28,203 tokens, PASS |
| `s02-firewall-change`, 3 runs | 32,531 FAIL, then 26,562 and 24,400 PASS |
| `s02-hidden-config-change`, 3 runs | 12,731 / 12,639 / 12,715 tokens, PASS |
| `s02-lost-response`, 3 runs | 32,556 / 33,866 / 34,732 tokens, PASS |

The `s02-firewall-change` failure was under the token budget, so another check failed, and I did not
capture which one. It passed in 6 of 6 reruns. In an earlier set of runs, `s02-lost-response` once
ended after a single request with no tool calls (1 of 15 runs).

## Open

- Router coverage on unseen incidents. An independent author who has seen neither the 20 incidents
  nor the prompt would give a fair number.
- Exercise 3 and the new case where the cause is a rare log line in a component the alert does not
  mention.
