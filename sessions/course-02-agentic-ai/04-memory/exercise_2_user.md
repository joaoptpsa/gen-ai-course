# Exercise 2 Rationale

Why `starter/reading_user.py` is built the way it is, what the checks showed and where it falls
short.

## Status

`check_recall.py` gives 10/10 through `starter/harness_user.py`. The starter gave 1/10.
`s04-stale-false-positive` and `s04-conflicting-shift-notes` each passed 3 of 3 runs with the
model. The upstream starter harness also passed each case in its one run, so these two cases do
not tell the starter and the final policy apart with `claude-haiku-5-5`.

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

## Measured Results

| Check | Result |
| --- | --- |
| `check_recall.py`, starter `reading_user.py` | 1/10, queries 3/6, SET-210 leaked |
| `check_recall.py`, first version | 10/10, queries 6/6 |
| `check_recall.py`, final | 10/10, queries 6/6 |
| Paraphrase probe, no model (deleted after the run) | 7/7 |
| `ruff check`, `basedpyright` | clean, 0 errors |

Runs with the model, `claude-haiku-5-5`, through `harness_user.py`:

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

`writing_user.py` is still the starter in this worktree, so `remember` saved each run's note at
confidence 1.0. Every save came after the report was decided, so it did not change a result.

## Open

- A case that the starter fails. With this model, a seed that the starter's text search cannot
  surface is more likely to discriminate than a stronger "trust memory" instruction. The README
  asks for one new case; I did not write it here.
- The conflict rule is coarse. Two shift notes on the same subject about different incidents are
  flagged as conflicting. Once exercise 3 writes a shift note per run, every pair of notes on a
  component will be flagged. Not measured.
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
- Three runs per case show the cases can pass, not how often they fail.
