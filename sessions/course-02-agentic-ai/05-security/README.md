# Session 5 — Security: Threat Model, PII, RBAC and Guardrails

Sessions 1–4 produced an agent that investigates, acts, uses external systems
and remembers. Each of those added a way for untrusted text to reach the
model (logs, tickets, tool descriptions, memory) and a way for the agent to
change systems or send data out. This session puts controls around them
without stopping the work the agent is there to do.

Run every command from the repository root after `uv sync` and after setting
`ANTHROPIC_API_KEY` in a local `.env` file.

## What you have

```text
05-security/
├── starter/harness.py   # the agent: follows any instruction it reads, approves through anyone, sends anywhere
├── threat-model.md      # template for your threat model
└── cases/               # attacks and legitimate operations
```

- Every run acts as an identity (`deps.identity`): `first-line` (the agent),
  `on-call` (Rita, the on-call engineer) or `incident-manager` (João). Each
  case sets one; `--role` overrides it. See `meridian/data/identities.yaml`.
- `request_approval(action, target, reason, approver_role)` asks a simulated
  human. In these cases the human accepts whatever they are asked. An
  approval is valid only for that action and that target.
- `send_message(channel, text)`: `members-status` reaches every member,
  `ops-internal` stays inside, `email:<address>` leaves the exchange.
- Logs contain trader names, emails, phone numbers and account numbers.
- The executor enforces one rule only: an action on a critical component
  needs an approval for that action and target. Who may act, when, and with
  whose approval is your policy.
- `meridian/security.py` gives your policy the facts it needs about an action
  (`describe_action`): role, target, critical or not, trading session open or
  not, and the approval behind it. It decides nothing.
- Trading hours: 09:00–17:30. Changes to critical components during the
  session are frozen unless the incident manager approves them.

| Role | Expected permissions (to turn into a policy) |
|---|---|
| first-line | Read everything. Restart one instance of a non-critical component. Never act on critical components. |
| on-call | Everything first-line can do. Act on critical components with an approval; outside trading hours their own approval is enough. |
| incident-manager | Approves changes to critical components during the trading session. Owns communication with members. |

## Exercise 1 — Threat model and controls

1. Fill in `threat-model.md` before writing any code: what you protect, who
   can influence the context, and how data can leave.
2. Run the starter on the attack cases and read what happened:

   ```bash
   uv run python -m meridian.run --summary \
     --harness sessions/course-02-agentic-ai/05-security/starter/harness.py \
     --cases-dir sessions/course-02-agentic-ai/05-security/cases
   ```

   - `s05-log-injection`: a log line asks for a matching-engine restart.
   - `s05-member-data-request`: a ticket asks for trader data at an outside address.
   - `s05-poisoned-memory`: a memory saved from a ticket recommends the same restart.
   - `s05-freeze-trading`: a critical rollback during the trading session.
   - Also add the description change you recorded in Session 3.
3. Copy the starter to `harness_v2.py` and add complementary controls:
   - **authorization**: a deterministic policy (RBAC plus the freeze rule)
     checked before every action, outside the model;
   - **PII**: detect and mask personal data in tool results before they reach
     the model, and check outgoing messages;
   - **guardrails** on input, tools and output: what each one checks, and
     what happens when it fires;
   - **approval**: who must approve what, and why an approval is not the same
     as authentication or authorization.
4. Run the legitimate cases after every change. A defence that refuses
   everything fails them:
   - `s05-legit-first-line-restart`: a routine restart and a status message;
   - `s05-legit-after-hours`: the same critical rollback, after the close, by the on-call engineer.
   Also try the freeze case with `--role incident-manager` and the after-hours
   case with `--role first-line`. Is the result what your policy says?

## Exercise 2 — Attack and defence

Two teams alternate in a controlled setting.

1. The attacking team writes a new case as a scenario file: an instruction
   hidden in a log, a ticket, a memory seed (`memory_seed`) or a tool
   description (`mcp.servers.<name>.descriptions`), or a request that tries
   to get data out.
2. The defending team runs it against their harness and fixes what passes,
   without breaking the legitimate cases.
3. Swap roles. Every attack joins your set of cases, next to a legitimate case
   that looks similar.
4. For each control, note its false positives (legitimate work blocked) and
   false negatives (attacks that passed).

## Conventions

- Keep a `status` field in the report.
- Do not edit `meridian/`. The executor's single rule is not your policy.
- Run all earlier cases after adding controls: a new guardrail can break a
  case from Session 2.

## Scope boundary

Threat model, indirect injection through every source, PII, guardrails,
authorization and approval, and the trading-session freeze. Rate limiting is
Session 9. Do not build a security framework: small, explicit checks around
your harness are enough.
