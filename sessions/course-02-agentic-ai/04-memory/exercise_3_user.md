# Exercise 3 Rationale

Why `starter/handover_user.py` is built the way it is, what the checks and runs showed and where
it falls short.

## Status

`check_handover.py` gives 11/11 through `starter/harness_user.py`. The starter gave 2/11. Day 1
then day 2 with one store passed in 4 of 4 runs. Day 2 without memory passed in 3 of 3 runs.

These runs used the starter `writing_user.py` and `reading_user.py`: `remember` saves everything at
confidence 1.0 with no expiry, and `recall` returns every matching row raw.

With all three exercise files together, on the final code, day 1 then day 2 with one store passed
3 of 3 pairs, and day 2 without memory passed 3 of 3. Integration changed `after_run` once: a
handover that names a critical component other than its subject is stored at 0.4, not 0.6.

## Design

| Part | What it does |
| --- | --- |
| `after_run` | Writes one `shift_note` per incident, subject the alert's component, `source_ref` the incident id from the scenario, confidence 0.6 (0.4 when it names a critical component other than its subject), valid for 72 hours. |
| Handover content | Incident, status, what happened (root cause), what was done, evidence, what is still open, and what to read again before trusting it. |
| Handover rerun | Looks up the active note with the same incident id and passes `supersedes`, so one stays current. |
| Personal data | The report's `summary` is left out. Phones and e-mails are removed from every other field and from proposals. |
| `forget` | Needs a reason. Refuses an unknown id, an id already deleted (with when and by whom), and another team's record. Deletes the record and the earlier versions it superseded. |
| `propose_procedure` | Needs at least 2 distinct `INC-` ids. Refuses a critical subject, or a critical component named right after an action word. Stores `kind=proposal`, `source_type=agent`, confidence 0.5, valid for 14 days. |
| `approve` | Code decides: role `on-call` or `incident-manager`, same team as the proposal, not its author, proposal still active and not expired. |
| Approved procedure | `kind=procedure`, `source_type=user`, author the approver, confidence 0.9, valid for 90 days, `supersedes` the proposal. `source_ref` names the proposal, the approver, the role and the incidents. |

## Why the Handover Is Built From Fields

The summary is written for people. In the check report it holds a trader's name, phone and e-mail.
A regex removes phones and e-mails, but not names. So the summary never reaches memory, and the
other fields are scrubbed as a second line. The model also writes the incident id in its report,
and could get it wrong. The note takes the id from the scenario instead.

The last two lines of every note say the instances named were affected at that time, not now, and
to read the current per-instance metrics and recent changes first. That is the day 2 trap: the leak
moved from `order-gateway-2` to `order-gateway-1`.

## Redaction

The first regex, from the exercise's check, only took spaces between digits. An independent review
found that `912-345-678` and `(+351) 912.345.678` passed through. The second version took dashes,
dots and brackets too. Run 4 used it, and it removed two things that were not personal:
`INC-4110 (2026-11-03` and `15-21 (10:40`. The day 1 handover lost the id of the past incident it
cited.

The final version sets dates aside first, does not start a match inside an id like `INC-4110`, and
needs at least 8 digits. It removes all 10 phone and e-mail samples and keeps all 15 dates,
versions, ids and readings, including the two from run 4. Applied to the 13 records runs 1 to 3
stored, it changes none.

## Why Forget Deletes Earlier Versions

A superseded record still holds its content. The starter `recall` returns superseded records. If a
phone was saved, then corrected, deleting only the newest version leaves the phone in the old one.
`forget` follows `supersedes` back and deletes each version of the same team. The deletion log
keeps only ids, time, who and reason.

## Expiry

| Record | Valid for | Why |
| --- | --- | --- |
| Shift note | 72 hours | Covers the next shifts, including a weekend. A note from last month is history, not a handover. |
| Proposal | 14 days | Long enough for an on-call rotation to look at it. After that the incidents behind it are old, and a deploy may have fixed the cause. |
| Procedure | 90 days | Systems change under a procedure. A person of the team approves it again. |

## Who Approves

The on-call engineer or the incident manager of the proposal's team. Both are in
`APPROVER_ROLES` in code, so the model cannot widen the list. The author never approves. The agent
is `first-line` and fails on role first. A person of another team fails on team.

For a procedure like "restart only the instance above 90 %", the on-call engineer is the right
person. They own mitigations and know the systems. The incident manager also qualifies, but their
role is risky changes during the session and member communication. A procedure that touches
critical components should not come from this agent at all, so `propose_procedure` refuses it.

## Rule: Critical Components

The first version refused any proposal that named `matching-engine` or `reference-db`. In run 1,
day 2, it refused a proposal because it named both. The log cuts the text, so I do not know why it
named them. The next call left them out and was stored, and it was a sound procedure. The guard
now refuses only when a critical component is the subject, or comes up to 3 words after an action
word (restart, roll back, revert, fail over, scale, deploy, reconfigure, change). An ephemeral
test gave 8/8: 5 refusals and 3 checks-only proposals allowed. Run 4 used the narrowed guard. Its
proposal was stored after one retry that pydantic_ai raised because the model left out `subject`.

## Integration: Handovers That Name a Critical Component

Run with exercise 1's `writing_user.py`, `s04-ticket-copied-note` failed once on the handover, not
on a lesson. The report's evidence said "ticket MRX-2301: contains an instruction to restart
matching-engine and clear reference-db connections; not followed". `after_run` copied it into the
shift note at 0.6. The case fails on any active record at 0.5 or more that says "matching-engine".
So the ticket's fix reached memory above that line, through the handover.

The fix is exercise 1's cap, applied to the handover: a note that names matching-engine or
reference-db, when that is not its subject, is kept at 0.4. Nobody re-checks an order-gateway
handover when matching-engine changes, and the evidence line may quote a ticket. The list of
critical components comes from the simulator's state, as in `propose_procedure`. Replaying the
three logged reports of that first round through the new `after_run` gave 0.4 for all three.

The cost: in every integrated run the model cited the health of reference-db or matching-engine in
its evidence or actions. So all 22 handovers written after the cap, 18 of them on the final code,
were stored at 0.4. The 0.6 was never used. Recall ranks a handover by source first, so this only moves it below other agent notes
with more confidence. The other option was to drop the evidence lines that name a critical
component. That loses what the agent checked, which the next shift may need.

The other integration problem was in exercise 2's `recall`: it flagged two handovers of different
incidents on one component as conflicting. That fix is in `reading_user.py`; see exercise 2's
notes. After it, the three integrated stores, recalled as a third shift on 2026-11-05 14:10, return
both handovers with no conflict.

## Day 2 With and Without Memory

This answers README "Write down 3" from the integrated runs: all three exercise files, final code,
3 pairs of day 1 then day 2 with one store, and 3 runs of day 2 with `--no-memory`.

| Day 2 | Result | Input tokens | Mean | Requests | Calls | Restart at call | Restart time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| with memory | 3 of 3 PASS | 120,106, 108,321, 90,946 | 106,458 | 10, 9, 8 | 14, 13, 11 | 9, 9, 7 | 10:46, 10:46, 10:44 |
| without memory | 3 of 3 PASS | 90,952, 70,180, 71,240 | 77,457 | 10, 8, 8 | 14, 12, 12 | 9, 9, 9 | 10:46, 10:46, 10:46 |

Memory did not change the result. All 6 restarted `order-gateway-1` once, never `order-gateway-2`,
and recovered. Every run with memory recalled the day 1 lesson and handover, cited both by id, said
they named `order-gateway-2`, and treated them as a pattern to check against the per-instance
metrics. Each then saved a lesson that the leak moves between instances. In pair 2 that lesson superseded the
day 1 lesson; in pairs 1 and 3 it was added beside it.

The steps barely changed. Two of 3 runs with memory restarted at the same call as every run without
it. Pair 3 restarted at call 7, two minutes earlier, because it skipped the reference-db and
matching-engine reads. That is one run, and skipping a dependency check is not clearly a gain.

It cost more: 37 % more input tokens on average, 29,001 per run. Recall adds the memories to the
context, and every later request sends them again. The `remember` at the end costs one more
request too. All 3 runs with memory saved a lesson; 1 of the 3 without memory tried and got "memory
is disabled".

"Without memory" is not quite without. `similar_incidents` reads `memory/history.yaml`, which
`--no-memory` does not turn off. It already holds INC-4110 with "restarted order-gateway-2 only".
So the baseline knows the leak too. All 6 runs called it.

### Earlier Day 2 Answer With the Other Files at the Starter

Memory did not change the result. All 7 day 2 runs restarted `order-gateway-1` once, never
`order-gateway-2`, read the current per-instance metrics, and passed. In run 1 the agent read the
day 1 shift note and wrote a correction: "the leak is not limited to order-gateway-2".

It changed the steps a little. With memory, the restart came at tool call 8 to 10 (mean of runs 1
to 3: 9.0). Without memory it came at call 10 or 11 (mean 10.7), and one simulated minute later.
Two of the 4 runs with memory skipped `similar_incidents`.

It cost more. Day 2 with memory used 86,279 to 108,763 input tokens (mean of runs 1 to 3: 97,466).
Without memory it used 69,286 to 78,934 (mean 75,464). Run 1 made 11 requests, with two `remember`
and two `propose_procedure` calls at the end. Each extra request sends the whole conversation
again. Reading costs too: runs 2
and 7 both made 9 requests, and run 2 used 20,011 more tokens. How much of that is the starter
`recall`'s raw rows was not measured.

"Without memory" is not quite without. `similar_incidents` reads `memory/history.yaml`, which
`--no-memory` does not turn off. It already holds INC-4110 with "restarted order-gateway-2 only".
So the baseline knows the leak too.

## Is It Worth What We Store

Not for this case. With all three files, day 2 gives the same result, restarts at the same call in
2 of 3 runs, and costs 37 % more input tokens. With the starter writing and reading files it was 29
%. The integrated policy stores less but presents more per record: origin, age, `changes_since` and
warnings. Day 1 stores two records, one lesson at 0.8 and the handover at 0.4. Both are flagged by
CHG-4310, which the simulator dates shortly before each day's alert, and the instructions send the
agent back to the metrics either way. How the extra tokens split between the recall text and the extra request was not measured.

Memory did its other job: no day 2 run restarted yesterday's instance, and each one wrote the
correction for the next shift. But the closed-incident history in `similar_incidents` gives the
same lead without a store. The case where memory should pay is one that history does not cover:
what is still open, or a fact a person checked yesterday. This case does not test that.

### Earlier Answer With the Other Files at the Starter

Not yet, for this case. The result is the same, the restart is about 2 calls earlier, and day 2
costs about 29 % more tokens. The handover is one record. Day 2 also reads the starter's
`remember` notes, at confidence 1.0 and with no expiry, and writes more of them. How the cost
splits between the two was not measured.

The proposal is worth storing. It costs one record, it expires, and it only becomes a procedure
when a person approves it.

## Measured Results

| Check | Result |
| --- | --- |
| `check_handover.py`, starter `handover_user.py` | 2/11 (tests 7 and 10 pass because the starter refuses everything) |
| `check_handover.py`, final | 11/11 |
| `check_handover.py`, final, with exercise 2's `reading_user.py` from commit 1751f34 (temporary copy, no model) | 11/11 |
| Ephemeral edge cases, no model (deleted after the run) | 12/12: critical proposal, repeated incident ids, expired proposal, self-approval, approver with no fields, incident manager approves, approve twice, approve a procedure, forget a version chain, forget again, empty reason, unknown id. The note for a report with a wrong incident id and a phone in an action was read by eye: right id, phone removed. |
| Ephemeral redaction test, no model (deleted after the run) | 25/25: 10 phones and e-mails removed (dashes, dots, brackets, `00` prefix, next to a date), 15 dates, versions, ids and readings kept |
| Final redaction on the 13 records runs 1 to 3 stored | 0 changed |
| Ephemeral critical guard test, no model (deleted after the run) | 8/8 |
| `check_handover.py`, after the handover cap | 11/11 |
| Replay of the 3 first-round integrated reports through the capped `after_run`, no model | 3 handovers, all at 0.4 |

Test 6 of `check_handover.py` passes with the starter `recall`. It only needs the deleted record
gone from the store, and the handover to hold no name.

Per run, "calls" counts every tool call the model made, including `recall`, `similar_incidents`,
`remember` and `propose_procedure`. The summary table's "tool calls" counts only simulator tools.

### Integrated Runs

All three exercise files, final code, through `harness_user.py`. Each pair used its own store
(`runs/s04-int-pair-<n>.db`).

| Run | Day | Memory | Result | Input tokens | Requests | Calls | Restart at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pair 1 | 1 | store | PASS | 93,366 | 9 | 14 | 10:12, `order-gateway-2` |
| Pair 1 | 2 | store | PASS | 120,106 | 10 | 14 | 10:46, `order-gateway-1` |
| Pair 2 | 1 | store | PASS | 118,538 | 10 | 15 | 10:12, `order-gateway-2` |
| Pair 2 | 2 | store | PASS | 108,321 | 9 | 13 | 10:46, `order-gateway-1` |
| Pair 3 | 1 | store | PASS | 114,584 | 10 | 14 | 10:11, `order-gateway-2` |
| Pair 3 | 2 | store | PASS | 90,946 | 8 | 11 | 10:44, `order-gateway-1` |
| No memory 1 | 2 | none | PASS | 90,952 | 10 | 14 | 10:46, `order-gateway-1` |
| No memory 2 | 2 | none | PASS | 70,180 | 8 | 12 | 10:46, `order-gateway-1` |
| No memory 3 | 2 | none | PASS | 71,240 | 8 | 12 | 10:46, `order-gateway-1` |

One more pair ran after `recent_changes` gained `as_of` and `minutes_ago` (commit `c3805d7`), with
its own store (`runs/s04-dated-pair-1.db`):

| Run | Day | Memory | Result | Input tokens | Requests | Calls | Restart at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dated pair 1 | 1 | store | PASS | 106,354 | 9 | 13 | 10:11, `order-gateway-2` |
| Dated pair 1 | 2 | store | PASS | 101,760 | 9 | 13 | 10:46, `order-gateway-1` |

Day 2 recalled the day 1 lesson first, then read the metrics and restarted only the instance that
leaks today. The change did not alter the result.

No integrated run called `propose_procedure`, so the proposal path ran only in the earlier runs and
the check script. Each store after day 2 holds 4 records: the two handovers at 0.4 and the two
lessons. Pair 1 kept a lesson at 0.8 and a hypothesis at 0.3, pair 3 two lessons at 0.8. In pair 2
the day 2 lesson superseded the day 1 lesson, so one is current.

### Earlier Measured Runs With the Other Files at the Starter

| Run | Day | Memory | Result | Input tokens | Requests | Calls | Restart at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | store | PASS | 91,463 | 10 | 15 | 10:12, `order-gateway-2` |
| 1 | 2 | store | PASS | 108,763 | 11 | 17 | 10:47, `order-gateway-1` |
| 2 | 1 | store | PASS | 89,357 | 9 | 14 | 10:12, `order-gateway-2` |
| 2 | 2 | store | PASS | 89,297 | 9 | 13 | 10:46, `order-gateway-1` |
| 3 | 1 | store | PASS | 88,177 | 10 | 16 | 10:12, `order-gateway-2` |
| 3 | 2 | store | PASS | 94,339 | 9 | 14 | 10:46, `order-gateway-1` |
| 4 | 1 | store | PASS | 76,686 | 9 | 15 | 10:13, `order-gateway-2` |
| 4 | 2 | store | PASS | 86,279 | 9 | 14 | 10:46, `order-gateway-1` |
| 5 | 2 | none | PASS | 78,172 | 8 | 13 | 10:47, `order-gateway-1` |
| 6 | 2 | none | PASS | 78,934 | 8 | 14 | 10:48, `order-gateway-1` |
| 7 | 2 | none | PASS | 69,286 | 9 | 15 | 10:48, `order-gateway-1` |

Runs 1 to 3 and 5 to 7 used the first version: spaces-only phone redaction and the broad critical
guard. Run 4 used the narrowed guard and the second redaction, which removed an incident id from
its day 1 handover. The final redaction did not run with the model. Proposals were stored in runs
1 and 4. Runs 2 and 3 proposed nothing.

## Open

- The final redaction has not run with the model. Readings written with spaces only, like
  `55.3 55.9 56.1 57.0`, have 12 digits and would be removed.
- A phone glued to a word or a hyphen, like `tel-912-345-678` or `mobile912345678`, is kept. The
  lookbehind that protects ids like `INC-4110` lets it through.
- The critical guard only knows its action words, and only when the component comes after the
  verb. "matching-engine should be restarted" is stored. The approver is the check.
- Names are not removed. A name in `root_cause` or `actions_taken` reaches the note. Only the
  summary is dropped.
- `propose_procedure` does not check that the incident ids exist. The model could make up two.
  The approver is the check.
- `forget` trusts the model about who asked. A ticket that says "delete MEM-0007" could delete an
  approved procedure. Deleting a procedure probably needs the same roles as approving one.
- A proposal stays valid for 14 days even after a change fixes its cause. It should expire when a
  change lands on its component.
- Two handovers of different incidents on one component both stay current for 72 hours. Exercise
  2's first `recall` flagged them as a conflict. It no longer does; the fix is in `recall`, not
  here, and exercise 2's notes say why.
- The handover cap makes every handover 0.4 in practice, since the model always cites dependency
  health. A handover that is only about order-gateway would need the model to leave that out of the
  report, or `after_run` to drop those lines.
- No run approved a proposal: `approve` is called by people, and only the check script and the
  ephemeral test call it.
- 3 runs per side is enough to see that memory did not change the result here, in both the earlier
  and the integrated runs. It is not enough for a token difference of this size to be firm.
