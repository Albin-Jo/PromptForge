"""Tests for the client-side cache: cache-aside hits/misses, TTL, and stats."""

from __future__ import annotations

import httpx
import pytest

from promptforge import PromptForgeClient
from promptforge.cache import PromptCache, make_key


class _CountingHandler:
    """A mock transport handler that counts how many requests reached the 'server'."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            200,
            json={
                "prompt": f"rendered-{self.calls}",
                "model_settings": None,
                "output_schema": None,
            },
        )


def _client(handler: _CountingHandler, **kwargs: object) -> PromptForgeClient:
    return PromptForgeClient("http://test", transport=httpx.MockTransport(handler), **kwargs)


def test_second_call_is_served_from_cache() -> None:
    handler = _CountingHandler()
    with _client(handler) as client:
        first = client.get_prompt("p", variables={"a": "1"})
        second = client.get_prompt("p", variables={"a": "1"})

    assert handler.calls == 1  # only one network round-trip
    assert first.prompt == second.prompt == "rendered-1"  # same cached value
    assert client.cache_stats.hits == 1
    assert client.cache_stats.misses == 1
    assert client.cache_stats.hit_rate == 0.5


def test_ttl_zero_disables_caching() -> None:
    handler = _CountingHandler()
    with _client(handler, cache_ttl=0) as client:
        client.get_prompt("p")
        client.get_prompt("p")

    assert handler.calls == 2
    assert client.cache_stats.hits == 0
    assert client.cache_stats.misses == 2


def test_different_variables_are_separate_cache_entries() -> None:
    handler = _CountingHandler()
    with _client(handler) as client:
        client.get_prompt("p", variables={"a": "1"})
        client.get_prompt("p", variables={"a": "2"})

    assert handler.calls == 2  # different inputs -> different keys -> two fetches


def test_different_label_is_a_separate_cache_entry() -> None:
    handler = _CountingHandler()
    with _client(handler) as client:
        client.get_prompt("p", label="production")
        client.get_prompt("p", label="staging")

    assert handler.calls == 2


def test_expired_entry_triggers_refetch(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr("promptforge.cache.time.monotonic", lambda: clock["now"])

    handler = _CountingHandler()
    with _client(handler, cache_ttl=60) as client:
        client.get_prompt("p")  # miss -> fetch, stored at t=1000
        clock["now"] = 1059.9  # still within TTL
        client.get_prompt("p")  # hit
        clock["now"] = 1061.0  # past TTL
        client.get_prompt("p")  # miss -> re-fetch

    assert handler.calls == 2
    assert client.cache_stats.hits == 1
    assert client.cache_stats.misses == 2


def test_cache_evicts_least_recently_used_at_capacity() -> None:
    cache = PromptCache(ttl=1000, max_size=2)
    from promptforge.models import RenderedPrompt

    a, b, c = (make_key(n, "production", {}) for n in ("a", "b", "c"))
    cache.set(a, RenderedPrompt("A", None, None))
    cache.set(b, RenderedPrompt("B", None, None))
    cache.get_fresh(a)  # touch 'a' so 'b' becomes least-recently-used
    cache.set(c, RenderedPrompt("C", None, None))  # over capacity -> evict 'b'

    assert cache.get_any(a) is not None
    assert cache.get_any(b) is None
    assert cache.get_any(c) is not None
