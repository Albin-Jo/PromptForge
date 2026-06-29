"""Unit tests for the SDK's ``record_trace`` — the client-side trace emitter.

These use an ``httpx.MockTransport`` so nothing touches the network: each test inspects the
outgoing ``POST /traces`` body or forces a failure. The end-to-end path (SDK -> real API ->
worker persist) is pinned in the API integration suite.
"""

from __future__ import annotations

import json

import httpx

from promptforge import PromptForgeClient, RenderedPrompt


def _client(handler) -> PromptForgeClient:
    return PromptForgeClient("http://test", transport=httpx.MockTransport(handler))


def _rendered() -> RenderedPrompt:
    """A server-rendered prompt carrying version identity (what get_prompt returns)."""
    return RenderedPrompt(
        prompt="Hello Ada",
        model_settings={"model": "openai/gpt-4o-mini"},
        output_schema=None,
        prompt_id="11111111-1111-1111-1111-111111111111",
        prompt_version_id="22222222-2222-2222-2222-222222222222",
        version_number=3,
    )


def test_record_trace_posts_version_linked_body_and_returns_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(202, json={"trace_id": "33333333-3333-3333-3333-333333333333"})

    with _client(handler) as client:
        trace_id = client.record_trace(
            _rendered(),
            input_tokens=10,
            output_tokens=5,
            latency_ms=420,
            status="ok",
        )

    assert trace_id == "33333333-3333-3333-3333-333333333333"
    assert seen["url"] == "http://test/traces"
    body = seen["body"]
    assert body["source"] == "sdk"
    assert body["model"] == "openai/gpt-4o-mini"  # defaulted from the version's model_settings
    assert body["prompt_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["prompt_version_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["input_tokens"] == 10
    assert body["output_tokens"] == 5
    assert body["latency_ms"] == 420
    # cost is never sent by the client — the server computes it from the pricing table.
    assert "cost_usd" not in body


def test_record_trace_swallows_errors_and_returns_none_when_api_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client(handler) as client:
        # Must not raise — tracing is telemetry and can't break the caller's request.
        result = client.record_trace(_rendered(), input_tokens=1, output_tokens=1)

    assert result is None


def test_record_trace_swallows_error_status_and_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    with _client(handler) as client:
        assert client.record_trace(_rendered(), status="ok") is None


def test_record_trace_swallows_non_json_success_body() -> None:
    """A 2xx with a non-JSON body must not raise — the 'never raises' guarantee covers it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=b"not json")

    with _client(handler) as client:
        assert client.record_trace(_rendered(), status="ok") is None


def test_record_trace_skips_invalid_status_without_posting() -> None:
    posted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posted
        posted = True
        return httpx.Response(202, json={"trace_id": "x"})

    with _client(handler) as client:
        assert client.record_trace(_rendered(), status="failed") is None  # not a valid status

    assert posted is False  # rejected locally — no pointless round-trip to a guaranteed 422


def test_record_trace_skips_when_no_model_available() -> None:
    posted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posted
        posted = True
        return httpx.Response(202, json={"trace_id": "x"})

    # A baked-in default has no model_settings and no version identity.
    default = RenderedPrompt(prompt="hi", model_settings=None, output_schema=None)
    with _client(handler) as client:
        assert client.record_trace(default) is None

    assert posted is False  # nothing was sent — there was no model to attribute it to
