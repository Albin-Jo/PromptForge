"""Shared test doubles for the LLM gateway.

The gateway takes its completion backend by injection, so any test that needs a
provider can substitute a fake instead of a network call. These helpers build the
OpenAI-shaped response LiteLLM returns and a recording backend, used by both the
gateway tests and the eval-judge tests (which drive the gateway underneath).

Not a ``test_*.py`` module, so pytest doesn't collect it; tests import from it.
"""

from types import SimpleNamespace
from typing import Any


def openai_shaped_response(
    content: str | None,
    *,
    model: str = "openai/gpt-4o-mini",
    finish_reason: str | None = "stop",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """An OpenAI-shaped completion response — the shape LiteLLM hands back."""
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def recording_backend(response: SimpleNamespace) -> tuple[Any, dict[str, Any]]:
    """A fake ``acompletion`` that records the kwargs it's called with, returns *response*."""
    captured: dict[str, Any] = {}

    async def backend(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return response

    return backend, captured
