# Pre-work — before Session 1

Allow 15–20 minutes for this setup before the first live class. The goal is
that class time is spent building, not installing tools or recovering accounts.

## What you need

- A laptop with a stable internet connection.
- Python 3.10 or newer.
- Git.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which manages
  Python and project dependencies for this course.
- An editor with an integrated terminal, such as VS Code or Cursor.
- A GitHub account
- An Anthropic Console account with billing enabled and a personal API key

An API key is a private credential that lets a program call the Anthropic API.
It is not the same as a Claude subscription. API usage may incur small charges,
depending on the model and volume used in class.

## Setup checklist

1. Install Python 3.10+ and Git.
2. Install uv.
3. Install your preferred editor.
4. Create or sign in to GitHub.
5. Create or sign in to the Anthropic Console, enable billing, and create an
   API key for personal use.
6. Clone the course repository once its URL is shared.
7. Open the cloned folder in your editor and terminal.
8. Run `uv sync` in the repository root. This creates the local environment and
   installs the dependencies declared in `pyproject.toml`.

## Keep your key safe

- Save the key only in a local `.env` file when instructed in class.
- Never paste it into a notebook, slide, chat, or GitHub repository.
- Never commit `.env`; the repository already ignores it.
- If a key is exposed, revoke it in the Anthropic Console immediately and
  create a new one.

## Diagnostic check

From a terminal, run:

```text
uv run python --version
git --version
uv --version
```

All commands should print a version number. In the first session we will run a
small repository diagnostic and make the first API call together, so no one has
to troubleshoot API credentials alone beforehand.

## Expected prior knowledge

You should be comfortable with Python variables, functions, lists/dictionaries,
imports, and running a Python file from a terminal. You do not need prior
experience with LLMs, APIs, asynchronous programming, Pydantic, or agent
frameworks.
