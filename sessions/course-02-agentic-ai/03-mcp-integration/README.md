# Session 3 — MCP: External Integration, Governance and Remote Access

Session 2 produced an agent with a context policy, selected tools and
idempotent actions. In this session the agent connects to the exchange's own
systems through MCP:

- a ticket system (Jira-like): projects MRX (operations) and MEM (member support);
- a monitoring platform (LogicMonitor-like): devices, alerts, datapoints, logs;
- a deployment platform: deployments, configuration changes, rollbacks, restarts.

These servers are written and published by other teams. You do not control
their catalog, their descriptions or the scopes of the credentials you are
given.

Run every command from the repository root after `uv sync` and after setting
`ANTHROPIC_API_KEY` in a local `.env` file.

## What you have

```text
03-mcp-integration/
├── starter/harness.py   # the agent, connected to every tool of the three servers
└── cases/               # incidents for this session
```

- The servers are in `meridian/mcp_servers/`. They are real MCP servers
  (FastMCP) that run in the same process as the agent and share its simulator:
  a restart through `deployments` changes what `monitoring` shows.
- `build_toolsets(deps)` in the harness decides which servers and tools the
  model gets. The starter exposes all of them with a prefix
  (`tickets_create_issue`, `monitoring_get_device_datapoints`, ...).
- The runbooks are still local files. They are procedures (Session 2), not an
  MCP server.

Look at the catalog before running anything:

```bash
uv run python -m meridian.mcp_servers inspect
uv run python -m meridian.mcp_servers inspect --server monitoring --full
```

It shows each server's version and publisher, the scopes granted to the
agent, and the approximate size of every tool definition. Those definitions
are sent to the model in every request.

## Exercise 1 — Select capabilities from an external catalog

Run the starter on the first case:

```bash
uv run python -m meridian.run \
  --harness sessions/course-02-agentic-ai/03-mcp-integration/starter/harness.py \
  --scenario sessions/course-02-agentic-ai/03-mcp-integration/cases/s03-alert-and-ticket.yaml
```

1. Read the trace. Which tools did the model use out of the 40-odd it was
   given? How many input tokens did the run use?
2. Copy the starter to `harness_v2.py` and apply your Session 2 selection
   policy to this catalog:
   - which tools this agent needs, per server, and why;
   - which capabilities overlap (for example a restart through
     `deployments.restart_workload` or through your own native tool from
     Session 2) and which one the agent should use;
   - when an MCP server is worth it here, and when a native tool is simpler.

   PydanticAI toolsets can be filtered and renamed
   (`MCPToolset(server).filtered(...)`, `.prefixed(...)`, `.renamed(...)`).
3. Compare both versions with `--summary`: tool calls, actions, input tokens.

## Exercise 2 — One incident, several sources

In `s03-alert-and-ticket` the same problem arrives three times: the
monitoring alert in the brief, ticket MRX-2210 and member complaint MEM-1187.

1. Run your harness. Did the agent open a second incident?
2. Design how the agent correlates sources: what it searches before creating
   anything, what makes two events the same incident, and what it records on
   the existing ticket (comment, link).
3. Run `s03-similar-but-different`: a gateway alert while an unrelated market
   data incident is open. Your correlation must not merge them.
4. Write one new case where correlation is hard (for example a complaint
   that describes a symptom with different words) and run it.

## Exercise 3 — Governance and access

Run your harness on the two remaining cases:

- `s03-description-change`: the monitoring server was upgraded overnight.
- `s03-scope-refused`: the ticket credentials were rotated.

1. For each case, classify what went wrong (or nearly did):
   - capability selection (your harness exposed the wrong thing);
   - server governance (someone changed the server or its descriptions);
   - credentials and scopes (the server refused because of the token).
2. Add a governance rule to your harness. For example, keep a lock file of
   the approved catalog (`inspect --json` gives versions and description
   hashes) and decide what happens when a server or a description changes:
   refuse the tool, use the approved version, or ask a human.
3. A tool description is not an instruction from your organisation. Record
   the changed description as a case for Session 5, where indirect injection
   is handled.
4. When a write is refused by scope, what should the agent do and report?
   Change the harness so that it neither insists nor looks for another way to
   write.

## Conventions

- Keep a `status` field in the report.
- Do not edit `meridian/`. Servers are other teams' systems: adapt your
  harness, not the server.
- Critical components (`matching-engine`, `reference-db`) cannot be changed by
  this agent. The executor rejects those actions.

## Trainer demo — remote access

The same tickets server over Streamable HTTP, with bearer tokens that carry
different scopes:

```bash
uv run python -m meridian.mcp_servers.http_demo serve
uv run python -m meridian.mcp_servers.http_demo client --token none
uv run python -m meridian.mcp_servers.http_demo client --token first-line
uv run python -m meridian.mcp_servers.http_demo client --token incident-manager
```

No token: the transport refuses the connection. A token without the scope:
the server refuses the call. A token with the scope: the call succeeds.

## Scope boundary

MCP integration, catalog selection, correlation of sources, server
governance and scopes. Defending against injected instructions is Session 5;
memory of earlier incidents is Session 4. Do not build an OAuth server or
support several transports from scratch.
