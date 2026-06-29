"""The SDK's own return types.

Kept deliberately plain (frozen dataclasses, stdlib only) so the SDK doesn't drag
Pydantic into a caller's app. ``RenderedPrompt`` mirrors the API's render response but
is *our* type — the wire format can evolve behind :meth:`RenderedPrompt.from_response`
without changing what callers see.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderedPrompt:
    """A finished prompt plus the model config to run it with.

    ``prompt`` is the rendered, ready-to-send text. ``model_settings`` is the version's
    provider/model/params bag (feed it straight to the gateway); ``output_schema`` is an
    optional JSON Schema for the expected output shape. Both may be ``None``.

    ``prompt_id`` / ``prompt_version_id`` / ``version_number`` identify the exact version
    this came from. The first two are opaque id strings the caller passes straight back
    to :meth:`PromptForgeClient.record_trace`, so a trace for the model call this prompt
    drives is attributed to the right version. They are ``None`` for a *baked-in default*
    (a caller's fallback text has no server version) — a trace can still be recorded, just
    without the version linkage.
    """

    prompt: str
    model_settings: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    prompt_id: str | None = None
    prompt_version_id: str | None = None
    version_number: int | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> RenderedPrompt:
        """Build a :class:`RenderedPrompt` from the API's JSON render response.

        The version-identity keys are read leniently (``.get``) so the SDK still parses a
        response from an older server that doesn't send them yet — they just stay ``None``.
        """
        return cls(
            prompt=data["prompt"],
            model_settings=data.get("model_settings"),
            output_schema=data.get("output_schema"),
            prompt_id=data.get("prompt_id"),
            prompt_version_id=data.get("prompt_version_id"),
            version_number=data.get("version_number"),
        )
