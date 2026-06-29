"""Rate-limiter port and adapters — a fixed-window counter per principal (Sprint 13 / Phase 11).

Same shape as the cache (:mod:`promptforge_api.cache`): the middleware depends on a small
:class:`RateLimiter` protocol, so production uses Redis, a bare/local run uses a no-op, and tests
inject an in-memory counter to prove throttling without standing up Redis.

The algorithm is a **fixed window**: the first request for a key starts a counter that expires after
the window; each request increments it; once it exceeds the limit the rest of the window is refused.
Simple and atomic (one ``INCR``); the more precise sliding-window/token-bucket variants are parked
in the backlog.

:class:`RedisRateLimiter` is **fail-open** — any Redis error degrades to "allowed", so a limiter
outage slows nothing and breaks nothing (a rate limiter must never become a new way to take the API
down).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, cast

import structlog

from promptforge_api.config import get_settings

_logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    """The verdict for one request: whether it's allowed and, if not, when to retry."""

    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    """Counts hits per key within a window and decides whether the next is allowed."""

    def hit(self, key: str) -> RateLimitDecision:
        """Record one request for *key* and return whether it's within the limit."""
        ...


class NullRateLimiter:
    """A limiter that never limits — the disabled / no-Redis default."""

    def hit(self, key: str) -> RateLimitDecision:
        return RateLimitDecision(allowed=True)


class InMemoryRateLimiter:
    """A process-local fixed-window limiter. For tests and single-process dev only.

    Not shared across processes, so it is **not** a production limiter (use Redis for that) — but
    it is a faithful fixed-window implementation, which is what makes the throttling test
    deterministic. ``clock`` is injectable so a test can advance time without sleeping.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._state: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def hit(self, key: str) -> RateLimitDecision:
        now = self._clock()
        window_start, count = self._state.get(key, (now, 0))
        if now - window_start >= self._window:
            window_start, count = now, 0  # window elapsed → reset
        count += 1
        self._state[key] = (window_start, count)
        self._prune(now)
        if count > self._limit:
            retry_after = max(1, int(window_start + self._window - now))
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
        return RateLimitDecision(allowed=True)

    def _prune(self, now: float) -> None:
        """Drop entries whose window has elapsed so the dict can't grow without bound.

        Only sweeps once the dict is non-trivially large, so the common path stays O(1).
        """
        if len(self._state) <= 1024:
            return
        expired = [k for k, (start, _) in self._state.items() if now - start >= self._window]
        for key in expired:
            del self._state[key]


class RedisRateLimiter:
    """A Redis-backed fixed-window limiter that fails open on any Redis error."""

    def __init__(
        self,
        redis_url: str,
        *,
        limit: int,
        window_seconds: int,
        timeout_seconds: float = 0.25,
        client: object | None = None,
    ) -> None:
        import redis

        # ``client`` is injectable so a test can exercise the INCR/EXPIRE/limit logic against a
        # fake without a live Redis; production builds the real client from the URL.
        self._redis: Any = client or redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        self._error = redis.RedisError
        self._limit = limit
        self._window = window_seconds

    def hit(self, key: str) -> RateLimitDecision:
        namespaced = f"ratelimit:{key}"
        try:
            # The sync client's incr/ttl are typed as ResponseT (Awaitable | Any); cast to the
            # int they actually return so the arithmetic below type-checks.
            count = cast(int, self._redis.incr(namespaced))
            if count == 1:
                # First hit in this window starts the clock; the counter self-expires after it.
                self._redis.expire(namespaced, self._window)
            if count > self._limit:
                ttl = cast(int, self._redis.ttl(namespaced))
                retry_after = ttl if ttl > 0 else self._window
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
            return RateLimitDecision(allowed=True)
        except self._error as exc:
            _logger.warning("rate_limiter_unavailable", error=str(exc))
            return RateLimitDecision(allowed=True)  # fail open


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """Return the process-wide limiter, chosen from settings.

    * ``rate_limit_requests == 0`` → :class:`NullRateLimiter` (disabled, the default).
    * enabled **with** a ``redis_url`` → :class:`RedisRateLimiter` (shared across processes).
    * enabled **without** Redis → :class:`InMemoryRateLimiter` + a warning. Per-process only (each
      worker counts independently), but enabling the limit is never a silent no-op.
    """
    settings = get_settings()
    if settings.rate_limit_requests <= 0:
        return NullRateLimiter()
    if settings.redis_url:
        return RedisRateLimiter(
            settings.redis_url,
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    _logger.warning(
        "rate_limiter_in_memory_fallback",
        reason="rate_limit_requests set but no redis_url; using per-process in-memory limiter",
    )
    return InMemoryRateLimiter(
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
