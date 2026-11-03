# Exercise 3 Rationale

Why `starter/actions_user.py` is built the way it is, what the checks showed and where it falls
short.

## Status

`check_actions.py` gives 4/4 through `starter/harness_user.py`. The starter gave 0/4. Each of the
four cases passed in one run with the model. That is one run per case, so it shows the cases can
pass, not how often they do.

## Design

| Part | What it does |
| --- | --- |
| `intent_key` | `{incident}:{action}:{target}`, built in code. A justified repeat gets `:2` or `:3`. |
| `attempts_done` | Asks `action_status` for each attempt key in turn and counts the completed ones. It returns `None` when the executor cannot answer. |
| `guarded` | Executes once under the key. On any error it asks `action_status(key)` and reports what the executor recorded. |
| `restart_instance` | Refuses critical components, reads the instance, asks the executor, then acts only if memory is above 90 %. |
| `restart_service` | Refuses critical components. Without `confirm=true` it returns a dry run with every instance, its memory and the impact. |
| `rollback_change` | Runs at most once per incident. A rejection on a critical component gets an `instead` saying to report the change as the root cause. |
| `refused` / `already_done` | Every blocked call says what was blocked, why, and what to do instead. |

The order inside `restart_instance` matters. It looks up earlier attempts before judging the
memory. A second request right after a restart therefore answers "already done", not "memory is
fine". Both are true, but only the first tells the model its restart happened.

## Rule 2: No Answer Is Not Nothing Happened

A lost answer comes in two forms, and they mean opposite things:

| Error | Where it happens | What `action_status(key)` says | Reported as |
| --- | --- | --- | --- |
| `No response from the executor ... (timeout)` | After the executor applied the action | `completed` | the executor's record, plus `lost_answer` |
| `restart_instance timed out` | In the tool, before the executor | `unknown_key` | `not_applied`, safe to call again |

Matching on the word "timeout" catches only the first. The second says "timed out", so a check
for "timeout" would hand the raw error to the model. `guarded` asks the executor after any error
instead of parsing the message. When `action_status` also fails, it answers `unknown`. The next call
looks the action up again before acting, so nothing runs twice.

## Rule 3: Where It Differs From the Text

The exercise says to restart "while memory is above 90 % (or it is not running)". An instance
that is not running here is always `restarting`, after a restart or an out-of-memory crash.
`rules.py` brings it back to `running` within a few ticks. A restart during a restart drops no
extra sessions, but it adds an effect and hides whether the first one worked. So
`restart_instance` refuses while the instance restarts and points to `wait_for_recovery`.

## Why a Key Chosen by the Model Is Weaker

- A model-chosen key is text the model writes again on every call, and the second call does not
  have to match the first. After a timeout the model has a reason to change it: the first try
  "failed", so it starts a fresh one. A new key looks like a new intent to the executor, so the
  restart runs again.
- Two agents, or one agent after its context is trimmed, do not share the earlier key. A key
  derived from the incident, action and target is the same for every caller who means the same
  thing.
- The model can also reuse a key for a different target. The executor answers `conflict`, and
  the model has to work out what that means.
- A derived key is code: the same intent gives the same key on every run. The model is never
  shown a key argument, so it cannot change one.

## When "One Intent, One Key" Is Wrong

The leak comes back in the same incident. `order-gateway-2` is restarted, its memory drops to the
baseline, and the leak climbs past 90 % again before the incident closes. The second restart is
justified, but `INC-2103:restart_instance:order-gateway-2` is already completed, so a plain key
answers "already done" and the instance runs out of memory.

`restart_instance` treats a completed restart followed by a running instance above 90 % as a new
intent with key `...:2`. The reason for acting is checked again first, so a repeated request right
after a restart still answers "already done". After `MAX_ATTEMPTS = 3` restarts it refuses and
says to report the leak and escalate, because a leak that keeps returning needs a fix, not
restarts.

Two other cases fit the same pattern but are not handled:

- The same rollback after its change was re-applied. The key says done, but the change is active
  again.
- A whole-service restart that was needed twice. It stays at one per incident, because each one
  drops every member session.

## Why `confirm` Is Not an Approval

`confirm=true` is an argument the model writes. It stops a whole-service restart that comes from
an old runbook or a guess, because the model first sees what it would drop. It is not a person
saying yes. Approvals by a person are Session 5.

## Measured Results

| Check | Result |
| --- | --- |
| `check_actions.py`, starter `actions_user.py` | 0/4 |
| `check_actions.py`, final | 4/4 |
| Ephemeral edge cases, no model (deleted after the run) | 8/8: timeout in the tool, `action_status` unavailable, restart in progress, leak returns, critical components, confirmed service restart repeated, critical rollback, unknown instance |
| `s02-firewall-change`, 1 run | 27,362 tokens, 19 tool calls, 1 action, PASS |
| `s02-hidden-config-change`, 1 run | 12,895 tokens, 9 tool calls, 0 actions, PASS |
| `s02-lost-response`, 1 run | 23,265 tokens, 14 tool calls, 1 action, PASS |
| `s02-noisy-gateway`, 1 run | 27,995 tokens, 13 tool calls, 1 action, PASS |

An independent review found nothing that would apply an action twice or report the wrong outcome.
It also probed lost answers on all three actions, a failure of `action_status` after a timeout,
and odd inputs.

These were the first runs through `harness_user.py` loading the `_user` files. Before that it
loaded the upstream `context.py`, `tool_selection.py` and `actions.py`.

`pydantic_ai` warned once per run set that `claude-haiku-5-5` rejected a replayed thinking block,
because the request prefix changed between turns. The likely cause is `search_tools` adding tools
mid-run, which is exercise 2's design. This is a hypothesis; I did not trace it. The run continued
without that turn's reasoning, and a changing prefix also defeats the prompt cache.

## Open

- More than one run per case. `s02-lost-response` passes when the model accepts "already done"
  and waits. One run does not show how often it does.
- The run summary shows no tool traces, so I did not confirm that the agent saw `already_done`
  rather than never asking twice.
