"""Client-side cache for rendered prompts (cache-aside, TTL, last-known-good).

A floating fetch asks for a *label* and the server resolves it to whatever version is
live; the same ``(name, label, variables)`` therefore yields the same rendered output
until a deploy moves the label. That makes the result safe to cache for a short window —
the **TTL is the staleness budget**: after a deploy, callers see the new version within
one TTL.

The cache deliberately **keeps expired entries** rather than evicting them on expiry, so
they can serve as *last-known-good* when the platform is unreachable (the stale-on-error
fallback). Eviction here is by capacity (LRU-ish: oldest-stored dropped), not by age.

In-memory and per-process by design (the documented v0.1 scope cut): an SDK imported into
an app caches in that app's memory. A shared/Redis client cache is post-v0.1.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from promptforge.models import RenderedPrompt

# A hashable cache key: prompt name, label, and the variable set (sorted so call order
# doesn't matter). Variable values are strings, so the tuple is fully hashable.
CacheKey = tuple[str, str, tuple[tuple[str, str], ...]]


def make_key(name: str, label: str, variables: dict[str, str]) -> CacheKey:
    """Build the cache key for one render request."""
    return (name, label, tuple(sorted(variables.items())))


@dataclass
class CacheStats:
    """Observable hit/miss counters — the 'cache hit rate observable' DoD line.

    A *hit* is a fresh (within-TTL) lookup served without a network call; a *miss* is a
    lookup that had to go to the server (absent or expired). Fallbacks are tracked
    separately and not counted as hits: *stale_served* when an expired entry is served
    because the platform was unreachable, *default_served* when the baked-in default is.

    Updates go through the ``record_*`` methods under a lock, because the client (and its
    cache) may be shared across threads — a bare ``+= 1`` is a non-atomic
    read-modify-write that would lose increments and skew the observed hit rate. Reading
    a counter directly is fine; ``hit_rate`` snapshots both under the lock for consistency.
    """

    hits: int = 0
    misses: int = 0
    stale_served: int = 0
    default_served: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def record_stale_served(self) -> None:
        with self._lock:
            self.stale_served += 1

    def record_default_served(self) -> None:
        with self._lock:
            self.default_served += 1

    @property
    def hit_rate(self) -> float:
        """Fraction of lookups served fresh from cache (0.0 when there were none)."""
        with self._lock:
            total = self.hits + self.misses
            return self.hits / total if total else 0.0


@dataclass
class _Entry:
    value: RenderedPrompt
    stored_at: float


class PromptCache:
    """Thread-safe, bounded, cache-aside store of rendered prompts.

    Thread-safe because the SDK may be shared across threads (e.g. a threaded web
    server). The lock guards only dict mutations, never a network call, so it can't
    serialize requests to the server.
    """

    def __init__(self, *, ttl: float, max_size: int = 256) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._lock = threading.Lock()
        self._entries: OrderedDict[CacheKey, _Entry] = OrderedDict()

    def get_fresh(self, key: CacheKey) -> RenderedPrompt | None:
        """Return the cached value if present and within TTL, else ``None``."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or time.monotonic() - entry.stored_at >= self._ttl:
                return None
            self._entries.move_to_end(key)  # mark most-recently-used
            return entry.value

    def get_any(self, key: CacheKey) -> RenderedPrompt | None:
        """Return the cached value regardless of age (last-known-good), or ``None``."""
        with self._lock:
            entry = self._entries.get(key)
            return entry.value if entry is not None else None

    def set(self, key: CacheKey, value: RenderedPrompt) -> None:
        """Store *value* under *key*, evicting the oldest entry if at capacity."""
        with self._lock:
            self._entries[key] = _Entry(value=value, stored_at=time.monotonic())
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)  # drop least-recently-used
