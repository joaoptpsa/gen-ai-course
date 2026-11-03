# Exercise 2 Rationale

Why `starter/tool_selection_user.py` is built the way it is, what the experiments showed and where
it falls short.

## Status

`check_routing.py` is not reliably met. Through `starter/harness_user.py`, 6 runs gave coverage
0.97, 0.93, 0.97, 0.93, 0.94 and 0.93 against the target of 0.95: 2 of 6 pass, mean 0.945. Size was
9.7 to 9.8 tools (target 10 or fewer) and no run offered a never-offered tool. On a holdout that an
independent author wrote, coverage is 0.88 to 0.90. The four cases passed in 11 of 12 runs. The
router is a model, so coverage moves about ±0.03 between runs on the same incidents.

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
resent in every later request. `context_user.py` now overrides it by name with the grouped digest that
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

These ran on 2026-10-27, before the `_user` split, when this router was still `starter/tool_selection.py`.
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

## Experiments With an Independent Holdout

`routing/holdout_user.yaml` has 20 incidents and 80 needs. A separate agent wrote it from the
catalog's one-line summaries alone. It never saw the 20 incidents, the router prompt or which tools
get missed. Its needs are stricter than the course's: 4.0 per incident against 3.55, and some count
`search_logs` as a need next to the core's `summarize_logs`. So its numbers sit lower and compare
variants, not the target. The variants below are structural, with no tool named in code and no
prompt wording changed. Each ran 3 times per set. Router tokens were not recorded for the first 3
runs of the current router on the 20 incidents:

| Variant | 20 incidents | Holdout | Size | Router tokens |
| --- | --- | --- | --- | --- |
| Current router | 0.97, 0.93, 0.97, 0.93, 0.94, 0.93 | 0.90, 0.88, 0.89 | 9.1 to 9.8 | ~2,170 to 2,300 |
| Fill free places with text matches | 0.96, 0.93, 0.96 | 0.94, 0.86, 0.91 | 9.9 to 10.0 | ~2,200 to 2,280 |
| Listing grouped by the thing a tool acts on | 0.93, 0.96, 0.92 | 0.91, 0.91, 0.88 | 9.0 to 9.8 | ~2,260 to 2,320 |
| Router limit cut to the room left (5, not 7) | 0.93, 0.94, 0.92 | 0.89, 0.88, 0.89 | 8.2 to 8.9 | ~2,190 to 2,270 |

- **Fill free places.** After the model's picks, code filled the places up to 10 with the tools whose
  name and summary share the rarest words with the incident line. An id prefix such as `MRX` or
  `ALR` matches the example in a summary. The fill added 0.25 tools per incident on the 20
  incidents and 0.8 on the holdout, and moved neither mean.
- **Grouped listing.** The router saw tools that share a word in both name and summary next to each
  other, such as `search_tickets`, `read_ticket` and `comment_ticket`. Coverage did not move.
- **Limit cut to the room left.** The prompt allows 7 picks, but beside the core and
  `wait_for_recovery` only 5 always fit. With the limit at 5 the model chose about one tool fewer
  and coverage stayed the same or fell.

All three were reverted. The spread inside one variant on the holdout was up to 0.08, larger than
any difference between variants.

The cap explains part of the misses on the 20 incidents. In 6 runs with the model's raw picks
recorded (3 of the current router, 3 of the grouped listing), 76 of 701 picks were cut by the cap of 10, and 9 of those were a need the selection then
missed: `check_link` on R02, R12 and R14, and `comment_ticket` on R17. On R17 the model often
picks `comment_ticket` last, after generic tools such as `exchange_status` and
`restart_instance`. `restart_instance` brings `wait_for_recovery`, and the core takes 4 places, so
`comment_ticket` is the 11th and is cut. On the holdout only 2 cut picks were needs. The rest of the
misses are tools the model never picked. Both come from the model's ranking, so the levers left
are prompt wording or a stronger router model. Wording fitted to these misses was tried and
reverted above.

## Measured Results

These numbers measured the `_user` files through `starter/harness_user.py`, on 2026-11-03, after
`harness_user.py` was fixed to load them (commit `601e301`). The router code is the same as on
2026-10-27. `context_user.py` and `actions_user.py` have changed since, so the case numbers are new.

| Check | Result |
| --- | --- |
| `check_routing.py`, 6 runs | coverage 0.97, 0.93, 0.97, 0.93, 0.94, 0.93; size 9.7 to 9.8; never-offered 0 |
| `check_routing.py` on the holdout, 3 runs | coverage 0.90, 0.88, 0.89; size 9.1 to 9.2; never-offered 0 |
| `s02-noisy-gateway`, 3 runs | 33,306 / 28,893 / 27,936 tokens, PASS |
| `s02-hidden-config-change`, 3 runs | 13,914 / 12,930 / 15,048 tokens, PASS |
| `s02-firewall-change`, 3 runs | 35,105 / 27,270 / 32,448 tokens, PASS |
| `s02-lost-response`, 3 runs | 26,388 / 26,679 tokens PASS, then 2,890 tokens FAIL |

The `s02-lost-response` failure was one request with no tool calls. The report said
`insufficient_information` and "Investigation not yet started". Two checks failed: "report claim"
and "recovery held for 5 ticks". It is the same failure as the 1 in 15 runs seen earlier, and it
comes from the agent's first request, not from the router.

The `s02-firewall-change` failure from 2026-10-27 (32,531 tokens, check not captured) did not come
back in these 3 runs, so it stays unexplained. In 2 of the 3 runs the router did not offer
`rollback_change`. The agent then found it with `search_tools`, at the cost of one more request:
35,105 and 32,448 tokens against 27,270 when it was offered. In all 3 `s02-noisy-gateway` runs the
agent found `restart_instance` the same way.

## Open

- The router does not reliably offer the fix tool when the incident names no change id. On
  `s02-firewall-change` it missed `rollback_change` in 2 of 3 runs. Another agent's runs of the new
  case `s02-feed-scale-change` (on `main`, not run here) had the same miss in both of its 2 budget
  failures out of 5 runs. `search_tools` recovers the tool, but the extra request can cross the budget.
- `s02-lost-response` can still end after one request with no tool calls (1 of 3 runs here).
