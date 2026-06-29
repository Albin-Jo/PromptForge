"""Failure-injection tests for the fallback chain — the 'pull the plug' DoD.

Each test forces the transport to fail and asserts the SDK still returns a usable prompt
(last-known-good, then baked-in default), and that *real* API errors are NOT papered over.
"""

from __future__ import annotations

import httpx
import pytest

from promptforge import (
    PromptForgeAPIError,
    PromptForgeClient,
    PromptForgeConnectionError,
    PromptNotFoundError,
    RenderedPrompt,
)


class _Switchable:
    """A transport handler that serves a value until ``down`` is set, then 'unplugs'."""

    def __init__(self) -> None:
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(
            200, json={"prompt": "live", "model_settings": None, "output_schema": None}
        )


def _client(handler: object, **kwargs: object) -> PromptForgeClient:
    return PromptForgeClient("http://test", transport=httpx.MockTransport(handler), **kwargs)


def test_serves_last_known_good_when_api_goes_down(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr("promptforge.cache.time.monotonic", lambda: clock["now"])

    handler = _Switchable()
    with _client(handler, cache_ttl=60) as client:
        warm = client.get_prompt("p", variables={"a": "1"})  # populate cache
        assert warm.prompt == "live"

        clock["now"] = 5000.0  # entry now far past TTL
        handler.down = True  # pull the plug

        survived = client.get_prompt("p", variables={"a": "1"})

    assert survived.prompt == "live"  # last-known-good, even though stale
    assert client.cache_stats.stale_served == 1
    assert client.cache_stats.default_served == 0


def test_serves_string_default_when_down_and_cache_cold() -> None:
    handler = _Switchable()
    handler.down = True
    with _client(handler) as client:
        result = client.get_prompt("p", default="fallback text")

    assert result == RenderedPrompt("fallback text", None, None)
    assert client.cache_stats.default_served == 1


def test_serves_rendered_prompt_default_when_down_and_cache_cold() -> None:
    handler = _Switchable()
    handler.down = True
    baked = RenderedPrompt("hi", {"model": "claude-opus-4-8"}, None)
    with _client(handler) as client:
        result = client.get_prompt("p", default=baked)

    assert result is baked
    assert result.model_settings == {"model": "claude-opus-4-8"}


def test_stale_cache_is_preferred_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr("promptforge.cache.time.monotonic", lambda: clock["now"])

    handler = _Switchable()
    with _client(handler, cache_ttl=60) as client:
        client.get_prompt("p")  # cache the live value
        clock["now"] = 5000.0
        handler.down = True
        result = client.get_prompt("p", default="never used")

    assert result.prompt == "live"  # last-known-good wins over the baked-in default
    assert client.cache_stats.stale_served == 1
    assert client.cache_stats.default_served == 0


def test_raises_when_down_with_no_cache_and_no_default() -> None:
    handler = _Switchable()
    handler.down = True
    with _client(handler) as client, pytest.raises(PromptForgeConnectionError):
        client.get_prompt("p")


def test_api_error_is_not_masked_by_default() -> None:
    """A real 422 must surface — falling back would hide a caller bug."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "missing variables: ['a']"})

    with _client(handler) as client, pytest.raises(PromptForgeAPIError):
        client.get_prompt("p", default="should not be used")


def test_not_found_is_not_masked_by_default() -> None:
    """A genuinely missing prompt must surface, not silently become the default."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    with _client(handler) as client, pytest.raises(PromptNotFoundError):
        client.get_prompt("missing", default="should not be used")
