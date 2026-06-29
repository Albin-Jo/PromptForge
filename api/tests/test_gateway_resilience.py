"""Unit tests for the gateway's error taxonomy, retry, and timeout (DoD: a flaky
provider triggers bounded retry, not a crash).

These tests construct real LiteLLM exceptions so we're verifying the *actual*
classification, then drive retry/timeout through injected backends with
``backoff_base=0`` so nothing sleeps. No network, no keys.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from structlog.testing import capture_logs

from promptforge_api.gateway import (
    LLMGateway,
    Message,
    ModelConfig,
    PermanentProviderError,
    RateLimitedError,
    TransientProviderError,
)
from promptforge_api.gateway.errors import classify_provider_error

_MODEL = "openai/gpt-4o-mini"
_MESSAGES = [Message(role="user", content="hi")]


def _ok_response(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        model=_MODEL,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=None,
    )


def _config() -> ModelConfig:
    return ModelConfig(model=_MODEL)


# --------------------------------------------------------------- classification
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            litellm.RateLimitError(message="x", llm_provider="openai", model=_MODEL),
            RateLimitedError,
        ),
        (
            litellm.Timeout(message="x", model=_MODEL, llm_provider="openai"),
            TransientProviderError,
        ),
        (
            litellm.APIConnectionError(message="x", llm_provider="openai", model=_MODEL),
            TransientProviderError,
        ),
        (
            litellm.InternalServerError(message="x", llm_provider="openai", model=_MODEL),
            TransientProviderError,
        ),
        (
            litellm.ServiceUnavailableError(message="x", llm_provider="openai", model=_MODEL),
            TransientProviderError,
        ),
        (
            litellm.AuthenticationError(message="x", llm_provider="openai", model=_MODEL),
            PermanentProviderError,
        ),
        (
            litellm.BadRequestError(message="x", model=_MODEL, llm_provider="openai"),
            PermanentProviderError,
        ),
        (
            litellm.NotFoundError(message="x", model=_MODEL, llm_provider="openai"),
            PermanentProviderError,
        ),
        (
            litellm.ContextWindowExceededError(message="x", model=_MODEL, llm_provider="openai"),
            PermanentProviderError,
        ),
        (TimeoutError(), TransientProviderError),
    ],
)
def test_classify_provider_error(exc: Exception, expected: type) -> None:
    result = classify_provider_error(exc)
    assert isinstance(result, expected)
    assert result.original is exc or isinstance(exc, TimeoutError)


def test_classify_unknown_5xx_is_transient() -> None:
    exc = litellm.APIError(status_code=503, message="x", llm_provider="openai", model=_MODEL)
    assert isinstance(classify_provider_error(exc), TransientProviderError)


def test_classify_unknown_4xx_is_permanent() -> None:
    exc = litellm.APIError(status_code=418, message="x", llm_provider="openai", model=_MODEL)
    assert isinstance(classify_provider_error(exc), PermanentProviderError)


def test_classify_reraises_non_provider_error() -> None:
    """A programming bug must not be disguised as a provider failure."""
    with pytest.raises(ValueError):
        classify_provider_error(ValueError("not a provider error"))


# ---------------------------------------------------------------------- retries
def _backend_raising(
    errors: list[Exception], response: SimpleNamespace
) -> tuple[Any, dict[str, int]]:
    """A fake backend that raises ``errors`` in order, then returns ``response``."""
    calls = {"n": 0}

    async def backend(**_kwargs: Any) -> SimpleNamespace:
        index = calls["n"]
        calls["n"] += 1
        if index < len(errors):
            raise errors[index]
        return response

    return backend, calls


async def test_transient_error_is_retried_then_succeeds() -> None:
    transient = litellm.InternalServerError(message="boom", llm_provider="openai", model=_MODEL)
    backend, calls = _backend_raising([transient, transient], _ok_response("recovered"))
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    result = await gateway.complete(config=_config(), messages=_MESSAGES)

    assert result.content == "recovered"
    assert calls["n"] == 3  # failed twice, succeeded on the third attempt


async def test_transient_error_exhausts_attempts_and_raises() -> None:
    transient = litellm.APIConnectionError(message="down", llm_provider="openai", model=_MODEL)
    backend, calls = _backend_raising([transient] * 5, _ok_response())
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    with pytest.raises(TransientProviderError):
        await gateway.complete(config=_config(), messages=_MESSAGES)
    assert calls["n"] == 3  # bounded by max_attempts, not a crash


async def test_rate_limit_is_retried() -> None:
    rate_limited = litellm.RateLimitError(message="429", llm_provider="openai", model=_MODEL)
    backend, calls = _backend_raising([rate_limited], _ok_response("after wait"))
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    result = await gateway.complete(config=_config(), messages=_MESSAGES)

    assert result.content == "after wait"
    assert calls["n"] == 2


async def test_permanent_error_is_not_retried() -> None:
    permanent = litellm.AuthenticationError(message="bad key", llm_provider="openai", model=_MODEL)
    backend, calls = _backend_raising([permanent], _ok_response())
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    with pytest.raises(PermanentProviderError):
        await gateway.complete(config=_config(), messages=_MESSAGES)
    assert calls["n"] == 1  # failed fast, no retry


# ---------------------------------------------------------------------- logging
async def test_retry_then_success_emits_log_trail() -> None:
    transient = litellm.InternalServerError(message="boom", llm_provider="openai", model=_MODEL)
    backend, _ = _backend_raising([transient], _ok_response())
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    with capture_logs() as logs:
        await gateway.complete(config=_config(), messages=_MESSAGES)

    events = [entry["event"] for entry in logs]
    assert "gateway_call_started" in events
    assert "gateway_call_retrying" in events  # the silent retry is now visible
    assert "gateway_call_succeeded" in events


async def test_permanent_failure_is_logged() -> None:
    permanent = litellm.AuthenticationError(message="bad key", llm_provider="openai", model=_MODEL)
    backend, _ = _backend_raising([permanent], _ok_response())
    gateway = LLMGateway(backend, max_attempts=3, backoff_base=0)

    with capture_logs() as logs, pytest.raises(PermanentProviderError):
        await gateway.complete(config=_config(), messages=_MESSAGES)

    assert "gateway_call_failed" in [entry["event"] for entry in logs]


# ---------------------------------------------------------------------- timeout
async def test_call_exceeding_timeout_raises_transient() -> None:
    async def slow_backend(**_kwargs: Any) -> SimpleNamespace:
        await asyncio.sleep(1)
        return _ok_response("too late")

    gateway = LLMGateway(slow_backend, max_attempts=1, timeout_seconds=0.01, backoff_base=0)

    with pytest.raises(TransientProviderError):
        await gateway.complete(config=_config(), messages=_MESSAGES)
