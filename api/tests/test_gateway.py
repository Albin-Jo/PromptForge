"""Unit tests for the LLM gateway — no network, no keys, no litellm.

The gateway takes its completion backend by injection, so every test substitutes a
fake ``acompletion`` and asserts on (a) the kwargs we forward to the provider and
(b) how we parse the provider's response. This is the "mocked provider" the DoD
asks for; the per-error-class half arrives with the taxonomy task.
"""

from types import SimpleNamespace

import pytest
from fakes import openai_shaped_response as _fake_response
from fakes import recording_backend as _recording_backend
from pydantic import ValidationError

from promptforge_api.gateway import Completion, LLMGateway, Message, ModelConfig


async def test_complete_parses_content_model_and_usage() -> None:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    backend, _ = _recording_backend(
        _fake_response("Hello there", model="openai/gpt-4o-mini", usage=usage)
    )
    gateway = LLMGateway(completion_fn=backend)

    result = await gateway.complete(
        config=ModelConfig(model="openai/gpt-4o-mini"),
        messages=[Message(role="user", content="hi")],
    )

    assert isinstance(result, Completion)
    assert result.content == "Hello there"
    assert result.model == "openai/gpt-4o-mini"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.total_tokens == 15


async def test_complete_forwards_messages_and_only_set_sampling_params() -> None:
    backend, captured = _recording_backend(_fake_response("ok"))
    gateway = LLMGateway(completion_fn=backend)

    await gateway.complete(
        config=ModelConfig(model="openai/gpt-4o-mini", temperature=0.2),
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ],
    )

    assert captured["model"] == "openai/gpt-4o-mini"
    assert captured["temperature"] == 0.2
    assert captured["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]
    # Unset knobs are not forwarded — the provider applies its own defaults.
    assert "max_tokens" not in captured
    assert "top_p" not in captured


async def test_provider_swap_is_config_only() -> None:
    """The same code path reaches two providers; only ``model`` changes (DoD)."""
    openai_backend, openai_kwargs = _recording_backend(
        _fake_response("a", model="openai/gpt-4o-mini")
    )
    anthropic_backend, anthropic_kwargs = _recording_backend(
        _fake_response("b", model="anthropic/claude-3-5-sonnet-latest")
    )
    messages = [Message(role="user", content="hi")]

    await LLMGateway(completion_fn=openai_backend).complete(
        config=ModelConfig(model="openai/gpt-4o-mini"), messages=messages
    )
    await LLMGateway(completion_fn=anthropic_backend).complete(
        config=ModelConfig(model="anthropic/claude-3-5-sonnet-latest"), messages=messages
    )

    assert openai_kwargs["model"] == "openai/gpt-4o-mini"
    assert anthropic_kwargs["model"] == "anthropic/claude-3-5-sonnet-latest"


async def test_complete_normalises_missing_content_and_usage() -> None:
    backend, _ = _recording_backend(_fake_response(None, finish_reason=None, usage=None))
    gateway = LLMGateway(completion_fn=backend)

    result = await gateway.complete(
        config=ModelConfig(model="openai/gpt-4o-mini"),
        messages=[Message(role="user", content="hi")],
    )

    assert result.content == ""  # None content normalised to empty string
    assert result.finish_reason is None
    assert result.usage is None


def test_model_config_rejects_unknown_keys() -> None:
    """A typo or unsupported param in the bag fails loudly (extra='forbid')."""
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({"model": "openai/gpt-4o-mini", "temprature": 0.2})


def test_model_config_requires_a_model() -> None:
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({"temperature": 0.2})


def test_model_config_validates_sampling_ranges() -> None:
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({"model": "openai/gpt-4o-mini", "temperature": 5.0})


def test_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "wizard", "content": "hi"})
