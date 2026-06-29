"""Server-side render cache: cache-aside behaviour and fail-open Redis adapter."""

from __future__ import annotations

import pytest
import redis
from sqlalchemy.orm import Session

from promptforge_api.cache import NullCache, RedisCache, get_cache
from promptforge_api.config import get_settings
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.services.prompts import PromptService, RenderVariableError


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
