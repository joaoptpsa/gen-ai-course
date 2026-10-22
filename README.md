# Generative AI Course

Working material for the Generative AI course. The repository grows session by
session and keeps runnable examples, implementation challenges, and evaluation
material close to the concepts taught in each class.

## Structure

```text
gen-ai-course/
├── docs/                 setup and pre-reads
├── meridian/             Course 2 simulator (Meridian Exchange)
├── sessions/
│   └── course-02-agentic-ai/        one folder per session
├── projects/
│   └── course-02-agentic-ai/        evolving project (Meridian Exchange incident response)
└── private/              trainer material and solutions (not committed)
```

### Docs

- [`docs/pre-work.md`](docs/pre-work.md) — initial environment setup.
- [`docs/course-01-pre-reads.md`](docs/course-01-pre-reads.md) — Course 1 reading and references, grouped by topic.
- [`docs/course-02-pre-reads.md`](docs/course-02-pre-reads.md) — Course 2 reading and references, grouped by topic.

### Course 2 — Agentic AI

- [`meridian/`](meridian/) — the Meridian Exchange simulator shared by every Course 2 session and the project.
- [`sessions/course-02-agentic-ai/01-agent-harness/`](sessions/course-02-agentic-ai/01-agent-harness/) — agent harnesses with PydanticAI: diagnose a failure, change one part, compare versions.
- [`sessions/course-02-agentic-ai/02-context-tools-skills/`](sessions/course-02-agentic-ai/02-context-tools-skills/) — context selection, tool interfaces, runbooks as procedures and idempotent actions.
- [`sessions/course-02-agentic-ai/03-mcp-integration/`](sessions/course-02-agentic-ai/03-mcp-integration/) — MCP servers for tickets, monitoring and deployments: catalog selection, correlation of sources, governance and scopes.
- [`sessions/course-02-agentic-ai/04-memory/`](sessions/course-02-agentic-ai/04-memory/) — memory between runs as data: origin, confidence, validity, conflicts, deletion, isolation and handover.
- [`sessions/course-02-agentic-ai/05-security/`](sessions/course-02-agentic-ai/05-security/) — threat model, PII, authorization, approvals, the trading-session freeze and attack/defence cases.
- [`projects/course-02-agentic-ai/`](projects/course-02-agentic-ai/) — the evolving Course 2 project.

## Getting started

This is a [uv](https://docs.astral.sh/uv/) project. Dependencies live in
`pyproject.toml`; we intentionally do not maintain a separate
`requirements.txt` with duplicate version information.

The course requires Python 3.10 or newer. `uv sync` will use a compatible
Python already installed on the computer; if none is available, uv can download
one automatically with its default configuration.

```text
uv sync
```

Create a local `.env` from `.env.example`, then add your personal API key. Do
not commit that file.

Run an exercise from the repository root with `uv run`, for example:

```text
uv run python -m meridian.run --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness.py --scenario sessions/course-02-agentic-ai/01-agent-harness/cases/s01-gateway-latency.yaml
```

Course 2 uses the `meridian` simulator, installed by `uv sync`. Its checks run
without an API key:

```text
uv run python -m pytest meridian/tests
```

## Principles

- Keep API keys local; never commit `.env` files.
- Build small, runnable examples before introducing abstractions.
- Use the official SDK and course-specific examples rather than copying entire external lessons.
