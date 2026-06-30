"""Server-side render cache: cache-aside behaviour and fail-open Redis adapter."""

from __future__ import annotations

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.cache import CacheStats, NullCache, RedisCache, get_cache
from promptforge_api.config import get_settings
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.services.prompts import (
    PromptNotFoundError,
    PromptService,
    RenderVariableError,
)


class FakeCache:
    """An in-memory cache implementing the Cache protocol, for asserting hits/misses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.store[key] = value


def _service(session: Session, cache: object) -> PromptService:
    return PromptService(PromptRepository(session), cache)


def test_repeat_render_is_served_from_cache_not_db(db_session: Session) -> None:
    """A cache hit returns the stored render even after the label moves (proving no DB read)."""
    cache = FakeCache()
    service = _service(db_session, cache)
    service.create_prompt(
        name="cached", description=None, content="v1 {{x}}", input_variables=["x"]
    )
    service.set_label(name="cached", label="production", version_number=1)

    first = service.render_by_label(name="cached", label="production", variables={"x": "hi"})
    assert first.prompt == "v1 hi"
    assert len(cache.store) == 1  # the render was cached

    # Deploy v2: a fresh DB read would render "v2 hi" — a cache hit must return "v1 hi".
    service.add_version(name="cached", content="v2 {{x}}", input_variables=["x"])
    service.set_label(name="cached", label="production", version_number=2)
    second = service.render_by_label(name="cached", label="production", variables={"x": "hi"})
    assert second.prompt == "v1 hi"  # served from cache, not re-rendered


def test_null_cache_always_reflects_current_label(db_session: Session) -> None:
    """With the no-op cache, every call re-renders, so a deploy is seen immediately."""
    service = _service(db_session, NullCache())
    service.create_prompt(name="live", description=None, content="v1 {{x}}", input_variables=["x"])
    service.set_label(name="live", label="production", version_number=1)
    assert (
        service.render_by_label(name="live", label="production", variables={"x": "a"}).prompt
        == "v1 a"
    )

    service.add_version(name="live", content="v2 {{x}}", input_variables=["x"])
    service.set_label(name="live", label="production", version_number=2)
    assert (
        service.render_by_label(name="live", label="production", variables={"x": "a"}).prompt
        == "v2 a"
    )


def test_unseen_invalid_variables_miss_and_fail_loudly(db_session: Session) -> None:
    """A never-cached, contract-violating variable set misses and raises (not served)."""
    service = _service(db_session, FakeCache())
    service.create_prompt(
        name="strict", description=None, content="Hi {{a}}", input_variables=["a"]
    )
    service.set_label(name="strict", label="production", version_number=1)
    with pytest.raises(RenderVariableError):
        service.render_by_label(name="strict", label="production", variables={})


def test_get_cache_returns_null_cache_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROMPTFORGE_REDIS_URL", raising=False)
    get_settings.cache_clear()
    get_cache.cache_clear()
    try:
        assert isinstance(get_cache(), NullCache)
    finally:
        get_settings.cache_clear()
        get_cache.cache_clear()


def test_get_cache_returns_redis_cache_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # from_url does not connect until a command is issued, so no live Redis is needed here.
    monkeypatch.setenv("PROMPTFORGE_REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    get_cache.cache_clear()
    try:
        assert isinstance(get_cache(), RedisCache)
    finally:
        get_settings.cache_clear()
        get_cache.cache_clear()


def test_rediscache_fails_open_on_redis_errors() -> None:
    """A Redis outage degrades to a miss (get) and a no-op (set), never an exception."""
    cache = RedisCache("redis://localhost:6379/0")  # not connected to until a command

    class _Down:
        def get(self, key: str) -> str:
            raise redis.RedisError("connection refused")

        def set(self, key: str, value: str, ex: int) -> None:
            raise redis.RedisError("connection refused")

    cache._redis = _Down()  # type: ignore[assignment]
    assert cache.get("k") is None  # swallowed -> treated as a miss
    cache.set("k", "v", ttl_seconds=10)  # swallowed -> no exception


# --------------------------------------------------------------------- cache stats (Sprint 29 T4)
def test_cache_stats_records_hits_and_misses_per_prompt() -> None:
    """The required wrapper unit test: a hit then a miss → a 0.5 hit-rate, kept per prompt."""
    stats = CacheStats()
    stats.record("p", hit=True)
    stats.record("p", hit=False)

    snap = stats.snapshot("p")
    assert (snap.hits, snap.misses, snap.total) == (1, 1, 2)
    assert snap.hit_rate == 0.5

    # An unseen prompt has zeros and an *undefined* rate (None), not a real 0%.
    empty = stats.snapshot("other")
    assert (empty.hits, empty.misses, empty.total) == (0, 0, 0)
    assert empty.hit_rate is None


def test_render_by_label_records_a_miss_then_a_hit(db_session: Session) -> None:
    """Driving the service: first render misses + caches, the second is served → 1 hit, 1 miss."""
    stats = CacheStats()
    service = PromptService(PromptRepository(db_session), FakeCache(), cache_stats=stats)
    service.create_prompt(
        name="counted", description=None, content="v1 {{x}}", input_variables=["x"]
    )
    service.set_label(name="counted", label="production", version_number=1)

    service.render_by_label(name="counted", label="production", variables={"x": "hi"})
    service.render_by_label(name="counted", label="production", variables={"x": "hi"})

    snap = service.render_cache_stats("counted")
    assert (snap.hits, snap.misses, snap.total) == (1, 1, 2)
    assert snap.hit_rate == 0.5


def test_failed_render_does_not_count_a_miss(db_session: Session) -> None:
    """A render that fails variable validation must not tally a miss — the hit-rate counts only
    genuinely-served prompts, so a bad-variable attempt leaves the counters untouched and the next
    *successful* render is the only miss."""
    stats = CacheStats()
    service = PromptService(PromptRepository(db_session), FakeCache(), cache_stats=stats)
    service.create_prompt(
        name="counted", description=None, content="v1 {{x}}", input_variables=["x"]
    )
    service.set_label(name="counted", label="production", version_number=1)

    with pytest.raises(RenderVariableError):
        service.render_by_label(name="counted", label="production", variables={"wrong": "v"})
    assert service.render_cache_stats("counted").total == 0

    service.render_by_label(name="counted", label="production", variables={"x": "hi"})
    snap = service.render_cache_stats("counted")
    assert (snap.hits, snap.misses) == (0, 1)


def test_unknown_prompt_render_does_not_grow_the_stats_dict(db_session: Session) -> None:
    """Rendering an unknown prompt must record nothing — otherwise the per-prompt dict grows on a
    request-controlled name. ``snapshot`` returns a real 1 if the buggy code recorded the miss, so
    asserting zero here is a genuine guard, not a tautology."""
    stats = CacheStats()
    service = PromptService(PromptRepository(db_session), FakeCache(), cache_stats=stats)

    with pytest.raises(PromptNotFoundError):
        service.render_by_label(name="ghost", label="production", variables={})

    assert stats.snapshot("ghost").total == 0


def test_render_cache_stats_404_for_unknown_prompt(db_session: Session) -> None:
    service = PromptService(PromptRepository(db_session), FakeCache(), cache_stats=CacheStats())
    with pytest.raises(PromptNotFoundError):
        service.render_cache_stats("nope")


def test_cache_endpoint_reports_counts_over_http(client: TestClient) -> None:
    """End-to-end: two renders flow through to the read endpoint's counts (a unique name isolates
    this test's tally in the process-wide recorder).

    Asserts the invariants only — the hit/miss split depends on the cache backend (NullCache in CI
    counts two misses; a live Redis counts a miss then a hit), but either way the total is two and
    the rate is consistent with the split.
    """
    name = "cache-http-stats"
    client.post("/prompts", json={"name": name, "content": "Hi {{x}}", "input_variables": ["x"]})
    client.put(f"/prompts/{name}/labels/staging", json={"version_number": 1})

    for _ in range(2):
        client.post(f"/prompts/{name}/render", json={"label": "staging", "variables": {"x": "a"}})

    body = client.get(f"/prompts/{name}/cache").json()
    assert body["prompt"] == name
    assert body["total"] == 2
    assert body["hits"] + body["misses"] == 2
    assert body["hit_rate"] == body["hits"] / 2
    assert body["ttl_seconds"] == get_settings().render_cache_ttl_seconds


def test_cache_endpoint_404_for_unknown_prompt(client: TestClient) -> None:
    assert client.get("/prompts/no-such-prompt/cache").status_code == 404


def test_cache_endpoint_requires_admin_when_auth_on(auth_client: TestClient) -> None:
    """Admin-gated like the queue health read: no token while auth is on → 401, not data."""
    assert auth_client.get("/prompts/whatever/cache").status_code == 401
