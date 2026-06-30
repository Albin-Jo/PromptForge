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

import threading
from dataclasses import dataclass
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


# --- render-cache hit/miss observability (Sprint 29 T4) -----------------------------------------
# The Cache protocol above is get/set only — it counts nothing. To surface a hit-rate we record the
# outcome where render_by_label already decides it (the prompt name is in scope there), into the
# recorder below, rather than parsing the prompt name back out of the opaque cache key in a wrapper.


@dataclass(frozen=True)
class CacheStatsSnapshot:
    """Cumulative render-cache outcomes for one prompt since the process started."""

    hits: int
    misses: int

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        # None (not 0.0) when there's been no render traffic — a "0/0" rate is undefined, and the UI
        # should say "no traffic yet" rather than imply a real 0% hit-rate.
        return self.hits / self.total if self.total else None


class CacheStats:
    """Thread-safe, per-prompt, in-process counters for render-cache hits and misses.

    Cumulative since process start and **per-process** (each worker keeps its own view), so this is
    an approximate operability signal, not an accounting record; the counters reset on restart. The
    lock guards the read-modify-write of the per-prompt counts under FastAPI's request threadpool.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, int] = {}
        self._misses: dict[str, int] = {}

    def record(self, name: str, *, hit: bool) -> None:
        """Record one render-cache outcome for *name*."""
        with self._lock:
            bucket = self._hits if hit else self._misses
            bucket[name] = bucket.get(name, 0) + 1

    def snapshot(self, name: str) -> CacheStatsSnapshot:
        """Return the cumulative hit/miss counts recorded for *name* (zeros if never seen)."""
        with self._lock:
            return CacheStatsSnapshot(
                hits=self._hits.get(name, 0), misses=self._misses.get(name, 0)
            )


@lru_cache
def get_cache_stats() -> CacheStats:
    """Return the process-wide render-cache stats recorder (shared by render and the read)."""
    return CacheStats()
