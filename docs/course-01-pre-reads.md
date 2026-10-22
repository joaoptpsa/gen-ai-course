# Course 1 — Pre-reads

Optional reading and reference material, grouped by topic. You do not need to
read everything before class.

## LLMs and APIs

- [OpenAI Python SDK](https://github.com/openai/openai-python) — official client,
  API usage, and streaming patterns. Licensed under
  [Apache-2.0](https://github.com/openai/openai-python/blob/main/LICENSE).
- [OpenAI Cookbook: streaming](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_stream_completions.ipynb)
  — streaming exercise reference.
- [OpenAI Cookbook: counting tokens](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb)
  — token-estimation exercise reference.

## Prompting and structured outputs

- [OpenAI Python SDK: structured outputs example](https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py)
  — Pydantic-based typed output reference.
- [OpenAI Cookbook: Structured Outputs](https://github.com/openai/openai-cookbook/blob/main/examples/Structured_Outputs_Intro.ipynb)
  — structured-output exercise reference. The Cookbook is licensed under
  [MIT](https://github.com/openai/openai-cookbook/blob/main/LICENSE).
- [Microsoft: prompt-engineering fundamentals](https://github.com/microsoft/generative-ai-for-beginners/tree/main/04-prompt-engineering-fundamentals)
  and [advanced prompts](https://github.com/microsoft/generative-ai-for-beginners/tree/main/05-advanced-prompts)
  — exercise-design references. Licensed under
  [MIT](https://github.com/microsoft/generative-ai-for-beginners/blob/main/LICENSE).

## Conversation, tools, and API integration

- [OpenAI: Function calling](https://developers.openai.com/api/docs/guides/function-calling)
  — strict tool schemas, function-call outputs, `call_id`, multiple calls and
  the tool-calling lifecycle.
- [OpenAI: Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
  — explicit history and API-managed conversation-state options.
- [FastAPI: Response models](https://fastapi.tiangolo.com/tutorial/response-model/)
  — typed public response contracts.
- [FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/)
  — endpoint tests through `TestClient`.

## Containers and integration

- [uv: Using uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
  — locked dependency installation and Docker layer patterns.
- [Docker: Optimize build cache](https://docs.docker.com/build/cache/optimize/)
  — ordering layers and reducing the build context.
- [Docker Compose: Control startup order](https://docs.docker.com/compose/how-tos/startup-order/)
  — health-based service dependencies.
