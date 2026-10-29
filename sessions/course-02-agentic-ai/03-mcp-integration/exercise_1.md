# Exercise 1 Rationale

Why `starter/incident_server_user.py` is built the way it is. Each section names a rule, what it
replaces and the evidence that led to it.

## The Problem

An alert, a ticket and a member complaint can describe one fault, and the agent opened one incident
for each. The opposite also happens: two faults at the same time look alike and merging them hides
one. `correlate(event, open_incidents)` returns the key of the open incident an event belongs to,
or `None` to open a new one.

A component is one of the five services of the simulated exchange in
`meridian/data/topology.yaml`: `order-gateway`, `matching-engine`, `market-data`, `settlement` and
`reference-db`. Each lists the components it depends on.

## How Many Incidents

The 22 events of `events/dev.yaml` make six groups. The grouping below follows the `incident:`
labels of that file; I did not label the events blind before reading them.

| Group | Events | Why they belong together |
| --- | --- | --- |
| A | E01-E06 | Gateway memory leak at 10:00. The complaint E04 never names the gateway. |
| B | E07 | A request, not a fault. |
| C | E08-E10, E12, E14, E15, E18 | Errors on the gateway and on settlement, which share `reference-db`. |
| D | E11, E13, E16, E17 | Latency on market-data, while C is open. |
| E | E19-E21 | The same leak as A, five hours later. |
| F | E22 | A request, not a fault. |

## Correlation Rules

| Rule | Where | Splits or merges |
| --- | --- | --- |
| A request is never an incident | `is_request` | Splits E07, E22 from everything |
| Only incidents within 30 minutes of their `last_seen` can match | `correlate` | Splits A from E |
| Same component joins the incident | `belongs_to` | Merges the gateway alert, ticket and complaint |
| Errors on two components with a shared dependency join | `shares_cause` | Merges C |
| A complaint takes its component from keywords in the text | `component_of` | Lets E04, E10, E13, E21 match |
| When several incidents match, the most recently seen wins | `correlate` | Keeps a late event with the live incident |

- The window compares against `last_seen`, not `first_seen`, so a long incident keeps absorbing
  events while it is active and a quiet one expires.
- Slow and errors are different symptoms. Latency on market-data next to errors on the gateway
  matches neither rule, so D stays apart from C even though D (11:05 to 11:21) runs inside C
  (11:00 to 11:30).
- Shared dependencies come from `load_topology()` and are followed through `depends_on`, so the
  rule needs no table of its own.
- Component names and keywords are regular expressions, so `market-data`, `market data` and
  `market_data` are one entry. They start at a word boundary, so `borders` is not `order`.

## The Hardest Rule

The shared cause. Errors on `order-gateway` at 11:00 and on `settlement` at 11:02 are one problem,
because both depend on `reference-db`. A rule on the component alone splits them and two people
start on the same fault. Merging on time alone does the opposite: it glues market-data latency to
gateway errors. The rule needs both conditions at once: both events are errors, and the
components' dependencies overlap.

Known limit: the overlap uses the dependencies of each component and not the component itself.
Errors on `order-gateway` and on `reference-db` do not match, although `reference-db` is the cause.
No event in `dev.yaml` covers it.

## Why This Belongs in a Server

- The model sees only the tool descriptions. Telling it in its instructions to "group events about
  the same problem" gives a different answer on every run and on every phrasing of a complaint.
- `correlate` is a function: the same 27 events always give the same grouping, and
  `check_correlation.py` measures it with no model (precision 1.00, recall 1.00, F1 1.00).
- The registry of open incidents and the clock live in the server. The model would have to read
  them from its context, where they are partial and old.
- Requests are filtered in `report_event` as well as in `correlate`. A `None` from `correlate`
  opens a ticket, so only a check before it keeps a request from becoming an incident.
- Every agent that connects to the server gets the same behavior, not only this one.

## The Tool Descriptions

The descriptions are the docstrings of `report_event` and `list_incidents`. They are all the model
knows about the server, so each says when to call the tool, what each argument is and what comes
back. `report_event` states that the model should report every signal before opening anything,
that `component` is omitted when unknown, and that requests are ignored.

## New Events

`events/dev.yaml` has five new events, E23 to E27. A rule of "same component within 30 minutes"
gets all five wrong and `correlate` gets all five right.

| Event | What it is | Why the naive rule fails |
| --- | --- | --- |
| E23 | Errors on settlement at 16:40 | Starts incident G. |
| E24 | Errors on the gateway at 16:43 | Different component, shared `reference-db`: the naive rule splits it. |
| E25 | "our orders are being rejected" | No component named: the naive rule cannot attach it. |
| E26 | "Request: raise the order rate limit" on the gateway | Same component and in the window: the naive rule merges a request into G. |
| E27 | "settlement batch failed again" | No component named, 24 minutes after G's last event. |

## Results

| Check | Result |
| --- | --- |
| `check_correlation.py` on 27 events | precision 1.00, recall 1.00, F1 1.00 (target 0.90) |
| `s03-alert-and-ticket` | PASS: attached to MRX-2210, 0 incidents created, recovery held |
| `s03-similar-but-different` | PASS: opened MRX-2401, MRX-2231 not linked, recovery held |

## A Fault Outside the Exercise

Both cases first failed on a bug in the monitoring team's server, not in this exercise.
`meridian/mcp_servers/monitoring.py:98` loops over `sim.state.links` and reads `.source` on each
item. `links` is a dict keyed by `(source, target)` tuples, so the loop gets tuples and
`monitoring_get_device` raises `'tuple' object has no attribute 'source'` on every call. The model
retries once, the run ends with "exceeded max retries", and the agent never acts.

`meridian/` is not edited. `gateway_user.py` hides `monitoring.get_device` from the model through
`BROKEN_TOOLS`, and the agent reads datapoints instead. The exercise 2 list of approved tools must
keep leaving it out.
