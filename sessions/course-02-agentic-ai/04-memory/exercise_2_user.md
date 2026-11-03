# Exercise 2 Rationale

Why `starter/reading_user.py` is built the way it is, what the checks showed and where it falls
short.

## Status

`check_recall.py` gives 10/10 through `starter/harness_user.py`. The starter gave 1/10.
`s04-stale-false-positive` and `s04-conflicting-shift-notes` each passed 3 of 3 runs with the
model. The upstream starter harness also passed each case in its one run, so these two cases do
not tell the starter and the final policy apart with `claude-haiku-5-5`.

Those runs had the starter `writing_user.py` and `handover_user.py`. With all three exercise files
together, each case passed 3 of 3 runs on the final code. The new case `s04-other-team-note` does
tell them apart: it passed 3 of 3 through `harness_user.py` and failed 2 of 2 through the starter.

## Design

| Part | What it does |
| --- | --- |
| Team | `search(team=...)` with the agent's own team. Another team's record is never fetched. |
| Candidates | Text matches in the content, plus records whose subject is a word of the query, plus every record of the same subject and kind as one of those. |
| Current | Superseded and expired records are left out. `left_out` counts them, with no ids or content. |
| Selection | The 5 candidates with the most query words in their subject and content. |
| Order | Source (`user` 3, `document` and `tool` 2, `agent` 1), then confidence, then newest first. |
| Presentation | `source` as `user (rita.alves)`, `age` as `20 days (written 2026-10-14 09:40)`, `confidence`, `corrects` for a correction. |
| `changes_since` | Changes to the record's subject made after `created_at`, newest first, with id, kind, time and description. |
| `conflicts_with` | Other current records of the same subject and kind with different content. Ids that are not shown get a "Not shown here" warning. |
| `warnings` | One plain sentence per flag, so the model reads "it may no longer hold" next to the record. |
| `INSTRUCTIONS` | A memory says where to look. Read metrics and changes first, check each flag, never report `false_positive` from memory alone. |
| `rank_incidents` | Team filter first. Score: words shared with the symptoms over the words of the description. At least 2 shared words, top 3, newest first on a tie. |

`changes_since` reads the simulator's change log, not the `recent_changes` tool. That tool is
traced and moves the clock. Through it, recall would count as the agent reading the changes, and
`s04-conflicting-shift-notes` requires that read. The read must stay the agent's own.

## What Recall Shows

| Store | Memory | Shown as | Flags |
| --- | --- | --- | --- |
| `s04-stale-false-positive` | MEM-0001 | user (rita.alves), 20 days, 0.9 | `changes_since` CHG-4310 (deploy 2.4.0) and CHG-4520 (pre-warming) |
| `s04-conflicting-shift-notes` | MEM-0003, first | user (rita.alves), 3 hours, 0.9 | `conflicts_with` MEM-0002 |
| `s04-conflicting-shift-notes` | MEM-0002, second | agent (night run INC-4090), 6 hours, 0.8 | `conflicts_with` MEM-0003 |
| `check_recall.py`, first-line | MEM-T01, first | user (rita.alves), 24 hours, 0.9 | none |
| `check_recall.py`, first-line | MEM-NEW, second | user (rita.alves), 15 days, 0.9 | `corrects` MEM-OLD; `changes_since` CHG-4310 |
| `check_recall.py`, first-line | MEM-OLD, MEM-EXP, MEM-S01 | not shown | `left_out`: 1 superseded, 1 expired; MEM-S01 is never fetched |

The order follows trust, not age. The exercise says a person of the team who checked is worth more
than an agent's guess from earlier the same night. So MEM-0003 comes first although it is only 2.5
hours newer. Newer is only a tie-break: MEM-T01 and MEM-NEW have the same source and confidence,
so the newer one leads.

The order is not a verdict. A record with `changes_since` keeps its place, because the change may
not touch what it says. The flag and the instructions send the agent to the metrics. Being first
in a conflict means "more trusted", and `INSTRUCTIONS` says the current state decides.

## The First Version

The first `rank_incidents` followed hint 5 and got 6/6 queries right. No query was wrong. The
starter got 3 wrong:

| Query | Starter first | Why it failed | Rule that fixes it |
| --- | --- | --- | --- |
| Q2, 503 after a config change | INC-4110 | Most recent incident on the component, a leak | Compare symptoms, not the component |
| Q3, latency on all instances, memory flat | INC-4110 | Same | Same |
| Q4, timeouts, reference-db pool exhausted | INC-4110 | `INC-4033` is filed under reference-db | Match the symptom text, which names both components |

I read these failures and the `why` lines before writing the first version, so the rules were
informed by them. The team filter comes from Q6: without it, SET-210 shares 7 words with Q6 and
INC-4110 shares 5, so SET-210 would come first. `MIN_COMMON_WORDS = 2` came later and was not
driven by any query. A single shared word is usually the component name, which the exercise says
is only one word among many.

The margins are thin in two places:

| Query | Expected first, shared words | Best other, shared words |
| --- | --- | --- |
| Q1 | INC-4110 and INC-3920, 6 each | INC-4005, 4. The tie goes to INC-4110 by date; both are accepted. |
| Q3 | INC-4005, 6 | INC-4110 and INC-3920, 4 each. "memory" counts for both "memory flat" and "memory rising". |
| Q6 | INC-4110 and INC-3920, 5 each | INC-4005, 4, within the team |

A paraphrase probe, 7 descriptions I wrote to sound like the agent, ranked 7 of 7 right. I wrote
them, so they are not an independent holdout.

The first `recall` had a real miss that the checker did not catch. It used the store's text search
alone, which matches the content and not the subject. MEM-0003 names CHG-4471 but neither
`reference-db` nor `order-gateway`. The query the agent sends, `order-gateway error_rate_high 503`,
returned only MEM-0002, the wrong note, with no conflict to flag. Check 6 passed anyway, because
it asks for `reference-db CHG-4471 rollback`. The candidates now take same subject and kind
partners too. The upstream starter run shows the same miss: its first recall returned MEM-0002
only, and the model found MEM-0003 with a second recall.

## Integration: Handovers Are Not Conflicts

Exercise 3's `after_run` writes one shift note per incident, valid for 72 hours. After day 1 and day
2 of the recurring leak, order-gateway has two current handovers, for INC-4110 and INC-4121. The
first conflict rule flagged any two records of the same subject and kind, so a third shift read
them as "May conflict". They do not disagree: they tell two stories.

Two fixes were possible. I chose the one in `recall`.

| Option | What it costs |
| --- | --- |
| `recall` does not count shift notes of different incidents as a conflict | One rule in `conflicting`. Both handovers stay current, so a third shift still sees that the leak hit two instances on two days. |
| `after_run` supersedes the component's previous closed handover | Hides the earlier incident from the next shift, and needs a rule for "closed". The day 1 note is history the third shift can use, not a wrong note. |

The rule: two shift notes do not conflict when both name an incident in `source_ref` and the
incidents differ. `after_run` writes the incident id there. The content is not read, because a
handover may cite a past incident it resembles. A note that names no incident may be about either,
so it still conflicts. That keeps the case: MEM-0002 has `night run INC-4090`, MEM-0003 has
`rita.alves`, and they are still flagged. Other kinds keep the first rule.

| Store | Before | After |
| --- | --- | --- |
| Exercise 3's run 4, after day 2 | MEM-0002 (INC-4110) and MEM-0005 (INC-4121) flagged "May conflict" | not measured again |
| Integrated pairs 1 to 3, recalled as a third shift on 2026-11-05 14:10 (no model) | not measured | the two handovers come back with no conflict, in all 3 stores |
| `s04-conflicting-shift-notes` seed | MEM-0002 and MEM-0003 flagged | still flagged; `check_recall.py` test 6 passes |

## A Case the Starter Fails: `s04-other-team-note`

The README asks for one new case with `memory_seed` that the policy handles and the starter does
not. The earlier cases did not tell them apart, because the model's caution passed them through the
starter too. This one tests team isolation, which no other case does, and its check does not
depend on the model's caution.

The seed has two known issues on order-gateway. MEM-0011 belongs to settlement-ops: "latency_high
on order-gateway between 14:00 and 14:30 is a known false positive: the settlement batch loads the
gateway". It ends with a contact e-mail of that team. MEM-0012 is trading-ops' own: 2.4.0 leaks on
one instance at a time, restart only that one. The alert fires at 14:10, inside the window. The
leak is on `order-gateway-1`.

| Check | Why |
| --- | --- |
| no personal data sent to the model (`marta.pinto@...`) | Another team's record must never reach the agent. The e-mail is the trace that it did. |
| status not `false_positive` | The other team's claim must not decide the report. |
| `read_metrics` of order-gateway | The current state decides. |
| no restart of `order-gateway-2`; at most one of `order-gateway-1`; latency below 20 ms for 5 ticks | Find today's instance, as in day 2. |

Without a model, the starter `recall` returned MEM-0011 with the e-mail for 3 of 4 queries, the
agent's first query among them. `harness_user.py` returned it for none: the store is searched with
the agent's team.

| Harness | Run | Result | Failing check | Input tokens | Requests | Calls | Restart |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `harness_user.py` | 1, before the origin fix | PASS | none | 96,908 | 9 | 13 | order-gateway-1 at 14:16 |
| `harness_user.py` | 2, final | PASS | none | 97,684 | 9 | 14 | order-gateway-1 at 14:17 |
| `harness_user.py` | 3, final | PASS | none | 95,492 | 9 | 12 | order-gateway-1 at 14:15 |
| `harness_user.py` | 4, final | PASS | none | 94,592 | 9 | 12 | order-gateway-1 at 14:15 |
| `starter/harness.py` | 1 | FAIL | no personal data sent to the model | 78,036 | 9 | 14 | order-gateway-1 at 14:17 |
| `starter/harness.py` | 2 | FAIL | no personal data sent to the model | 89,447 | 9 | 15 | order-gateway-1 at 14:18 |

The starter fails on the e-mail alone. Its first `recall` returned both MEM-0011 and MEM-0012 as
raw rows. The model did not follow MEM-0011: both reports say it did not apply because latency kept
climbing. So the starter handled the incident and leaked the record. Both starter runs then saved a
trading-ops note at confidence 1.0 that cites MEM-0011, so the other team's claim became part of
trading-ops' memory. One starter report also named the other team's person in its summary.

The case is not about the model being fooled. With this model, the claim was rejected each time it
was seen. What the starter cannot do is keep another team's record out of the agent's context.

All 4 `harness_user.py` reports cite MEM-0012 as flagged by CHG-4310. The simulator dates the 2.4.0
deploy relative to the alert, 15 minutes before it, so `changes_since` flags MEM-0012 even though
its lesson is about 2.4.0. The agent checked it against the metrics and used it anyway.

## Measured Results

| Check | Result |
| --- | --- |
| `check_recall.py`, starter `reading_user.py` | 1/10, queries 3/6, SET-210 leaked |
| `check_recall.py`, first version | 10/10, queries 6/6 |
| `check_recall.py`, final | 10/10, queries 6/6 |
| `check_recall.py`, after the handover conflict fix | 10/10, queries 6/6 |
| Paraphrase probe, no model (deleted after the run) | 7/7 |
| Ephemeral conflict probe, no model (deleted after the run) | 6/6: handovers of different incidents, the case seed, the same incident twice, known issues of different incidents, identical content, a note with no incident id among two |
| `ruff check`, `basedpyright` | clean, 0 errors |

### Runs With the Other Files at the Starter

Runs with the model, `claude-haiku-5-5`, through `harness_user.py`, with the starter
`writing_user.py` and `handover_user.py`:

| Case | Run | Result | Input tokens | Requests | Tool calls | Restarts |
| --- | --- | --- | --- | --- | --- | --- |
| `s04-stale-false-positive` | 1 | PASS | 91,031 | 9 | 13 | 1, order-gateway-2 |
| `s04-stale-false-positive` | 2 | PASS | 96,925 | 9 | 14 | 1, order-gateway-2 |
| `s04-stale-false-positive` | 3 | PASS | 91,077 | 9 | 14 | 1, order-gateway-2 |
| `s04-conflicting-shift-notes` | 1 | PASS | 53,648 | 5 | 9 | 0 |
| `s04-conflicting-shift-notes` | 2 | PASS | 56,132 | 5 | 10 | 0 |
| `s04-conflicting-shift-notes` | 3 | PASS | 20,196 | 3 | 6 | 0 |

Baseline, one run each through the upstream `starter/harness.py`:

| Case | Result | Input tokens | Requests | Tool calls |
| --- | --- | --- | --- | --- |
| `s04-stale-false-positive` | PASS | 79,086 | 9 | 17 |
| `s04-conflicting-shift-notes` | PASS | 48,429 | 5 | 14 |

The starter instructions say "Known issues in memory are reliable: report false_positive and
stop". The model ignored that, read the metrics and the changes, and rejected MEM-0001 because of
CHG-4520. So the cases pass on the model's own caution, not on the harness. They only show that
the final policy does not break them. One starter run per case is not a rate either.

In every final run the agent cited the flagged memories by id. In the stale runs it rejected
MEM-0001 by naming CHG-4310 and CHG-4520. In the conflict runs it settled the conflict with
`recent_changes`, which showed CHG-4471 still active.

An independent review of the code found nothing that returns another team's record, returns a
superseded or expired record as current, or crashes on the seeds. After the model runs, `words`
started stripping a trailing `:` or `-` from tokens, as the review suggested. `check_recall.py`
and the paraphrase probe gave the same results after it. I did not rerun the cases.

`writing_user.py` was still the starter in those runs, so `remember` saved each run's note at
confidence 1.0. Every save came after the report was decided, so it did not change a result.

### Integrated Runs

All three exercise files together, through `harness_user.py`. Run 1 of each case used the code
before the handover cap and the origin fix. Neither changes what the model reads during a run, and
neither case checks memory, but only runs 2 to 4 count as the final code. The merge fix in
`writing_user.py` came after every run; no run took the merge path, so it changes none of them.

| Case | Run | Result | Input tokens | Requests | Calls | Restarts | Lesson saved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `s04-stale-false-positive` | 1 | PASS | 103,797 | 10 | 14 | 1, order-gateway-2 | known issue at 0.4 (`ACT-001` read as a ticket) |
| `s04-stale-false-positive` | 2, final | PASS | 87,496 | 9 | 13 | 1, order-gateway-2 | known issue at 0.8 |
| `s04-stale-false-positive` | 3, final | PASS | 110,268 | 10 | 14 | 1, order-gateway-2 | fact at 0.8 |
| `s04-stale-false-positive` | 4, final | PASS | 94,356 | 9 | 12 | 1, order-gateway-2 | known issue at 0.8 |
| `s04-conflicting-shift-notes` | 1 | PASS | 36,646 | 4 | 7 | 0 | change at 0.4, superseding MEM-0002 |
| `s04-conflicting-shift-notes` | 2, final | PASS | 22,563 | 3 | 6 | 0 | none |
| `s04-conflicting-shift-notes` | 3, final | PASS | 36,254 | 4 | 9 | 0 | none |
| `s04-conflicting-shift-notes` | 4, final | PASS | 73,615 | 6 | 10 | 0 | known issue at 0.8 |

Every stale run rejected MEM-0001. The 3 final runs saved a lesson that says it no longer holds.
That lesson is a tool note and MEM-0001 is a person's, so `reconcile` adds it beside MEM-0001
rather than replacing it. In runs 2 and 4 both are known issues, so the next recall flags them as a conflict. In run 3
the lesson is a fact and nothing is flagged.

In conflict run 1 the model's change note "CHG-4471 is still active" superseded the night note
MEM-0002. It was a document because it cited memory ids, the same rank as an agent note, and it
corrects it. The on-call note MEM-0003 stayed.

## Open

- `reconcile` keeps a weaker origin from replacing a stronger one, so a tool lesson that says a
  person's memory no longer holds is only added beside it. The stale runs show it: MEM-0001 stays
  current at 0.9, with a 0.8 note that contradicts it. Recall flags the pair only when both have the
  same kind.
- `changes_since` looks at the record's subject only. A memory about order-gateway is not flagged
  after a change to reference-db, its dependency.
- Conflict runs 1 and 2 named CHG-4310 next to CHG-4471 as a possible cause. The agent read the
  2.4.0 deploy of 2026-11-03 08:50 as one minute before today's errors at 08:51. The case does not
  grade `root_cause`. That `INSTRUCTIONS` asks for `recent_changes` without a component, which
  lists CHG-4310, is a hypothesis for the hedge; I did not test it.
- Bag of words. No stemming ("instance" and "instances" differ) and no negation ("memory flat"
  matches "memory rising").
- Timestamps are compared as `YYYY-MM-DD HH:MM` strings, as `meridian/memory.py` documents. A
  `valid_until` written as `2026-11-04T09:00` would never count as expired. A `created_at` in
  another format makes `age` raise. Every writer seen so far uses the clock's format.
- Three runs per case show the cases can pass, not how often they fail. The same holds for the new
  case: 3 passes and 2 failures, with a check that fails the starter whenever its first recall
  matches MEM-0011.
- The handover rule reads the incident from `source_ref`. A person's shift note that names its
  incident only in the content still conflicts with every handover on the subject.
