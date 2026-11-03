# Exercise 3 Rationale

Why `starter/handover_user.py` is built the way it is, what the checks and runs showed and where
it falls short.

## Status

`check_handover.py` gives 11/11 through `starter/harness_user.py`. The starter gave 2/11. Day 1
then day 2 with one store passed in 4 of 4 runs. Day 2 without memory passed in 3 of 3 runs.

These runs used the starter `writing_user.py` and `reading_user.py`: `remember` saves everything at
confidence 1.0 with no expiry, and `recall` returns every matching row raw. The numbers below must
be measured again once exercises 1 and 2 are merged.

## Design

| Part | What it does |
| --- | --- |
| `after_run` | Writes one `shift_note` per incident, subject the alert's component, `source_ref` the incident id from the scenario, confidence 0.6, valid for 72 hours. |
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

## Day 2 With and Without Memory

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

Not yet, for this case. The result is the same, the restart is about 2 calls earlier, and day 2
costs about 29 % more tokens. The handover is one record. Day 2 also reads the starter's
`remember` notes, at confidence 1.0 and with no expiry, and writes more of them. How the cost
splits between the two was not measured.
The case where memory should pay is one the closed-incident history does not cover: what is still
open, or a fact a person checked yesterday. This case does not test that.

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

Test 6 of `check_handover.py` passes with the starter `recall`. It only needs the deleted record
gone from the store, and the handover to hold no name.

Per run, "calls" counts every tool call the model made, including `recall`, `similar_incidents`,
`remember` and `propose_procedure`. The summary table's "tool calls" counts only simulator tools.

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
  2's `recall` (commit 1751f34) flags them as a conflict: on run 4's store after day 2, MEM-0002
  (INC-4110) and MEM-0005 (INC-4121) came back as "May conflict". Day 2 itself reads only the day 1
  note, so these runs are not affected; a third shift within 72 hours would be. Either `recall`
  should not count shift notes of different incidents as a conflict, or `after_run` should
  supersede the last closed handover of the component.
- No run approved a proposal: `approve` is called by people, and only the check script and the
  ephemeral test call it.
- 3 runs per side is enough to see that memory did not change the result here. It is not enough
  for a token difference of this size to be firm.
