"""What the lab of session 9 shares: loading your starter file, and the models."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STARTER = HERE.parent / "starter"
SOLUTIONS = (
    HERE.parents[3] / "private" / "course-02-agentic-ai" / "reference" / "session-09"
)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # keep the terminal quiet
SMALL = os.getenv("ANTHROPIC_MODEL_SMALL", "claude-haiku-5-5")
LARGE = os.getenv("ANTHROPIC_MODEL_LARGE", "claude-sonnet-5-5")
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}  # USD per 1M tokens (in, out)
BACKUP_MARKUP = 1.25  # provider B: the same strong model in the lab, sold 25% dearer (simulated second provider)


def use_solutions() -> bool:
    """Trainer only: LAB_SOLUTIONS=1 runs the solutions instead of starter/, without touching starter/."""
    return os.environ.get("LAB_SOLUTIONS") == "1" and SOLUTIONS.is_dir()


def load_starter(name: str):
    folder = SOLUTIONS if use_solutions() else STARTER
    spec = importlib.util.spec_from_file_location(f"s09_{name}", folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"s09_{name}"] = module
    spec.loader.exec_module(module)
    return module


def patient(model: Any) -> Any:
    """An Anthropic model that retries more when rate-limited. Built inside the run's event loop."""
    if not (isinstance(model, str) and model.startswith("anthropic:")):
        return model
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    client = AsyncAnthropic(max_retries=6)
    provider = AnthropicProvider(anthropic_client=client)
    return AnthropicModel(model.removeprefix("anthropic:"), provider=provider)


def models(chosen: Any) -> dict[str, Any]:
    """{"small": ..., "large": ..., "backup": ...}. The real Anthropic models, or the test doubles the tests give.

    "backup" stands for a second provider. In the lab it is the same strong model, so the exercise runs with one API key."""
    if isinstance(chosen, dict):
        return {"backup": chosen["large"], **chosen}
    if isinstance(chosen, str):
        return {
            "small": f"anthropic:{SMALL}",
            "large": f"anthropic:{LARGE}",
            "backup": f"anthropic:{LARGE}",
        }
    return {"small": chosen, "large": chosen, "backup": chosen}


def model_name(model: Any) -> str:
    return (
        model.removeprefix("anthropic:")
        if isinstance(model, str)
        else getattr(model, "model_name", "test")
    )
