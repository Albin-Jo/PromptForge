"""Validated *inputs* to the gateway.

These are Pydantic models on purpose: they validate data that arrives from outside
the trusted core — a version's free-form ``model_settings`` JSONB bag (Sprint 3)
and caller-supplied chat messages — so a malformed config or role fails loudly here
rather than as an opaque provider error. The gateway's *outputs* (``Completion``)
are plain dataclasses instead, since they're produced internally (CLAUDE.md: Pydantic
at the boundary, dataclasses inside).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """One chat-completion message. The provider-neutral request unit."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class ModelConfig(BaseModel):
    """Structured form of a version's ``model_settings`` bag.

    ``model`` is a LiteLLM provider-prefixed identifier — ``"openai/gpt-4o-mini"``,
    ``"anthropic/claude-3-5-sonnet-latest"`` — so *swapping providers is editing this
    one string*. The remaining fields are optional sampling controls; only the ones
    actually set are forwarded, leaving the provider to apply its own defaults.

    ``extra="forbid"``: an unrecognised key (a typo in the bag, a param we don't yet
    support) is rejected at validation time rather than silently dropped. Provider
    API keys are **not** here — they come from the environment (12-factor); the bag
    only ever carries non-secret call parameters.
    """

    model_config = ConfigDict(extra="forbid")

    # Provider+model selector, e.g. "openai/gpt-4o-mini". The only required field.
    model: str = Field(min_length=1)
    # Sampling controls. Ranges follow the common provider contract; LiteLLM
    # normalises these across vendors. None = "unset", so we don't forward it.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: list[str] | None = None
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    # Best-effort determinism where the provider supports it.
    seed: int | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        """Map this config to ``litellm.acompletion`` keyword arguments.

        ``exclude_none`` forwards only the fields that were set, so an unset knob
        means "use the provider default" rather than "send null".
        """
        return self.model_dump(exclude_none=True)
