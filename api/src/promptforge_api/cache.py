"""Server-side cache port and adapters for hot prompt fetches.

The render-by-label endpoint is the path the SDK hammers, so it sits behind a read-through
cache: render once, serve the cached bytes until the short TTL lapses. The cache is an
**accelerator, never a hard dependency** — if Redis is unreachable the API must still serve
from Postgres. Two design rules enforce that:

* The service depends on the :class:`Cache` *protocol*, not on ``redis`` — so the domain
  stays clean and tests inject a fake (mirrors how the gateway injects ``completion_fn``).
* :class:`RedisCache` is **fail-open**: any Redis error is logged and swallowed, degrading
  to a cache miss (reads) or a no-op (writes), so an outage slows us down but never breaks us.

When no ``redis_url`` is configured the factory returns a :class:`NullCache`, so local runs
and tests need no Redis at all.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

import structlog

from promptforge_api.config import get_settings

_logger = structlog.get_logger(__name__)


class Cache(Protocol):
    """A minimal string key/value cache with per-entry expiry."""

    def get(self, key: str) -> str | None:
        """Return the cached value for *key*, or ``None`` on miss."""
        ...

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """Store *value* under *key*, expiring after *ttl_seconds*."""
        ...


class NullCache:
    """A cache that stores nothing — every read misses. The no-Redis default."""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        return None


class RedisCache:
    """A Redis-backed cache that fails open: a Redis error never breaks a request."""

    def __init__(self, redis_url: str, *, timeout_seconds: float = 0.25) -> None:
        # Imported lazily so the dependency is only needed when caching is enabled.
        import redis

        # Bounded connect/read timeouts are what make fail-open real: without them a
        # *hung* Redis (reachable but not responding) would block the request thread
        # indefinitely, turning the accelerator into a hard dependency. A timeout raises
        # redis.TimeoutError (a RedisError subclass), so it degrades to a miss below.
        # decode_responses=True so we exchange str, not bytes, with the service layer.
        self._redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        # The base class for connection/timeout failures — what we swallow to fail open.
        self._error = redis.RedisError

    def get(self, key: str) -> str | None:
        try:
            value = self._redis.get(key)
        except self._error as exc:
            _logger.warning("cache_unavailable", operation="get", error=str(exc))
            return None
        return value if value is None else str(value)

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        try:
            self._redis.set(key, value, ex=ttl_seconds)
        except self._error as exc:
            _logger.warning("cache_unavailable", operation="set", error=str(exc))


@lru_cache
def get_cache() -> Cache:
    """Return the process-wide cache: Redis if configured, else a no-op NullCache."""
    settings = get_settings()
    if settings.redis_url:
        return RedisCache(settings.redis_url)
    return NullCache()
