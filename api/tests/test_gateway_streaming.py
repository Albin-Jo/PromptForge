"""Tests for streaming: the gateway's ``stream()`` and the SSE ``/complete`` endpoint.

A fake streaming backend stands in for the provider — no network, no keys. The
endpoint tests build an app and override ``get_gateway`` so no real provider (or DB)
is touched; SSE frames are asserted against the buffered response text.
"""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from fastapi.testclient import TestClient

from promptforge_api.gateway import LLMGateway, Message, ModelConfig, StreamChunk
from promptforge_api.main import create_app
from promptforge_api.routers.gateway import get_gateway

_MODEL = "openai/gpt-4o-mini"


def _chunk(content: str | None, finish_reason: str | None = None) -> SimpleNamespace:
    """A LiteLLM-shaped stream chunk (delta + finish_reason)."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)
        ]
    )


def _stream_backend(chunks: list[SimpleNamespace], *, fail_with: Exception | None = None) -> Any:
    """A fake ``acompletion(stream=True)``: yields *chunks*, optionally then raises."""

    async def backend(**_kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        async def agen() -> AsyncIterator[SimpleNamespace]:
            for chunk in chunks:
                yield chunk
            if fail_with is not None:
                raise fail_with

        return agen()

    return backend


def _opening_failure_backend(error: Exception) -> Any:
    """A fake backend that fails before any chunk (opening the stream)."""

    async def backend(**_kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        raise error

    return backend


def _slow_first_token_backend(delay: float, chunks: list[SimpleNamespace]) -> Any:
    """A fake backend whose first chunk only arrives after *delay* seconds.

    Mirrors litellm's real behaviour: ``await acompletion(stream=True)`` returns
    promptly, but the network round-trip happens on the first ``__anext__``.
    """

    async def backend(**_kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        async def agen() -> AsyncIterator[SimpleNamespace]:
            await asyncio.sleep(delay)
            for chunk in chunks:
                yield chunk

        return agen()

    return backend


# ----------------------------------------------------------------- gateway.stream
async def test_stream_yields_deltas_in_order() -> None:
    chunks = [_chunk("He"), _chunk("llo"), _chunk(None, finish_reason="stop")]
    gateway = LLMGateway(_stream_backend(chunks))

    received = [
        chunk
        async for chunk in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        )
    ]

    assert [c.content for c in received] == ["He", "llo", ""]
    assert received[-1].finish_reason == "stop"
    assert all(isinstance(c, StreamChunk) for c in received)


async def test_stream_skips_empty_keepalive_chunks() -> None:
    chunks = [_chunk(None), _chunk("hi"), _chunk(None)]  # leading/trailing empties dropped
    gateway = LLMGateway(_stream_backend(chunks))

    received = [
        chunk
        async for chunk in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        )
    ]

    assert [c.content for c in received] == ["hi"]


async def test_stream_times_out_on_slow_first_token() -> None:
    """The deadline bounds time-to-first-token, not just the (lazy) opening await."""
    from promptforge_api.gateway import TransientProviderError

    gateway = LLMGateway(_slow_first_token_backend(1.0, [_chunk("late")]), timeout_seconds=0.01)

    with pytest.raises(TransientProviderError):
        async for _ in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        ):
            pass


async def test_stream_handles_empty_stream() -> None:
    gateway = LLMGateway(_stream_backend([]))

    received = [
        chunk
        async for chunk in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        )
    ]

    assert received == []


async def test_stream_skips_chunk_with_no_choices() -> None:
    """A usage-only / malformed chunk lacking choices is dropped, not crashed on."""
    chunks = [SimpleNamespace(choices=[]), _chunk("hi")]
    gateway = LLMGateway(_stream_backend(chunks))

    received = [
        chunk
        async for chunk in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        )
    ]

    assert [c.content for c in received] == ["hi"]


async def test_stream_classifies_midstream_failure() -> None:
    transient = litellm.InternalServerError(message="boom", llm_provider="openai", model=_MODEL)
    gateway = LLMGateway(_stream_backend([_chunk("partial")], fail_with=transient))

    from promptforge_api.gateway import TransientProviderError

    with pytest.raises(TransientProviderError):
        async for _ in gateway.stream(
            config=ModelConfig(model=_MODEL), messages=[Message(role="user", content="hi")]
        ):
            pass


# ------------------------------------------------------------------ SSE endpoint
def _client(gateway: LLMGateway) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_gateway] = lambda: gateway
    return TestClient(app)


def _request_body() -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": "hi"}], "config": {"model": _MODEL}}


def test_endpoint_streams_tokens_then_done() -> None:
    chunks = [_chunk("He"), _chunk("llo"), _chunk(None, finish_reason="stop")]
    client = _client(LLMGateway(_stream_backend(chunks)))

    response = client.post("/complete", json=_request_body())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert 'event: token\ndata: {"content": "He"' in body
    assert 'event: token\ndata: {"content": "llo"' in body
    assert "event: done" in body
    assert "event: error" not in body


def test_endpoint_emits_error_event_on_midstream_failure() -> None:
    permanent = litellm.AuthenticationError(message="bad key", llm_provider="openai", model=_MODEL)
    client = _client(LLMGateway(_stream_backend([_chunk("partial")], fail_with=permanent)))

    response = client.post("/complete", json=_request_body())

    assert response.status_code == 200  # headers already sent before the failure
    body = response.text
    assert 'event: token\ndata: {"content": "partial"' in body
    assert "event: error" in body
    assert "PermanentProviderError" in body
    assert "event: done" not in body


def test_endpoint_emits_error_event_on_opening_failure() -> None:
    permanent = litellm.AuthenticationError(message="bad key", llm_provider="openai", model=_MODEL)
    client = _client(LLMGateway(_opening_failure_backend(permanent)))

    response = client.post("/complete", json=_request_body())

    assert response.status_code == 200
    body = response.text
    assert "event: error" in body
    assert "event: token" not in body
    assert "event: done" not in body


def test_endpoint_emits_generic_error_on_unexpected_failure() -> None:
    """A non-GatewayError mid-stream still rides the stream, without leaking detail."""
    client = _client(LLMGateway(_stream_backend([_chunk("partial")], fail_with=ValueError("boom"))))

    response = client.post("/complete", json=_request_body())

    assert response.status_code == 200
    body = response.text
    assert 'event: token\ndata: {"content": "partial"' in body
    assert "event: error" in body
    assert "InternalError" in body
    assert "boom" not in body  # internal detail not leaked to the client
    assert "event: done" not in body


def test_endpoint_rejects_unknown_body_keys() -> None:
    client = _client(LLMGateway(_stream_backend([_chunk("hi")])))

    response = client.post("/complete", json={**_request_body(), "bogus": 1})

    assert response.status_code == 422
