"""Celery queue/worker health — a read-only view of the async backbone (Sprint 29 T3).

The async work (evals, scans, trace-ingest) runs on Celery, but the API has no in-app view of it —
only single-job polling, with Flower as a separate operator tool. This surfaces the two signals that
answer "are the workers keeping up?":

* **Queue depth (backlog)** — how many messages wait in each broker queue. With a Redis broker each
  queue is a list, so ``LLEN`` over the known queues gives it. This is the robust signal: a bounded
  read that works even with **zero workers online**, and the first thing to climb when something's
  wrong.
* **Worker liveness + active tasks** — read via Celery's inspect API, which broadcasts a control
  message and waits for workers to reply. Best-effort: it depends on workers answering within a
  timeout, so a failure here degrades to ``None`` counts rather than failing the whole view.

Deliberately **no "failed" count**: Celery exposes no cheap failure counter (failures live only in
the result backend as keys that expire in an hour, or in Flower's own event DB), so failure history
stays Flower's job. :func:`read_queue_health` is **pure** over an injected :class:`QueueInspector`,
so it's tested with a fake snapshot and no live broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, cast

import structlog
from celery import Celery

from promptforge_api.celery_client import get_celery
from promptforge_api.config import get_settings

_logger = structlog.get_logger(__name__)

# The worker's queue topology (promptforge_worker.celery_app: DEFAULT/EVALS/SCANS/TRACES). The API
# does not import the worker package (producer/consumer decoupling — see celery_client), so the
# names are mirrored here; keep in sync. "celery" is the default queue (health ping, webhook
# delivery); the rest are routed by task name.
QUEUE_NAMES = ("celery", "evals", "scans", "traces")


@dataclass(frozen=True)
class QueueDepth:
    """Pending (not-yet-delivered) message count for one broker queue."""

    name: str
    depth: int


@dataclass(frozen=True)
class RawQueueSnapshot:
    """The raw broker reads: per-queue backlog plus best-effort worker stats.

    ``worker_count``/``active_count`` are ``None`` when worker inspection failed even though the
    queue reads succeeded — distinct from ``0`` (broker reachable, genuinely no workers online).
    """

    queues: list[QueueDepth]
    worker_count: int | None
    active_count: int | None


@dataclass(frozen=True)
class QueueHealth:
    """The shaped health view: backlog, worker liveness, and whether the broker was reachable."""

    available: bool
    workers: int | None
    active: int | None
    queued: int | None
    queues: list[QueueDepth] | None


class QueueProbeError(Exception):
    """The broker could not be reached for the queue-depth read — health degrades to unavailable."""


class QueueInspector(Protocol):
    """Reads live broker/worker state.

    ``snapshot`` raises :class:`QueueProbeError` when the broker is unreachable, so the service can
    return an "unavailable" view instead of letting a 500 escape.
    """

    def snapshot(self) -> RawQueueSnapshot: ...


def read_queue_health(inspector: QueueInspector) -> QueueHealth:
    """Map a raw broker snapshot into the health view, degrading gracefully when the broker is down.

    Pure policy over the injected inspector (mirrors :func:`evaluate_alerts`): a test passes a fake
    that returns a snapshot or raises, with no live broker in the loop.
    """
    try:
        snap = inspector.snapshot()
    except QueueProbeError:
        return QueueHealth(available=False, workers=None, active=None, queued=None, queues=None)
    return QueueHealth(
        available=True,
        workers=snap.worker_count,
        active=snap.active_count,
        queued=sum(q.depth for q in snap.queues),
        queues=snap.queues,
    )


class CeleryQueueInspector:
    """Real :class:`QueueInspector`: queue depth via a bounded Redis read, workers via inspect.

    Two failure postures, matching the cache's fail-open discipline (``cache.RedisCache``):

    * the **queue-depth** read is the liveness signal — if the broker can't be reached for it we
      raise :class:`QueueProbeError`, so the whole view degrades to "unavailable";
    * **worker inspection** is best-effort — any failure logs and yields ``None`` counts, but the
      queue depths still come back.
    """

    def __init__(self, app: Celery, *, broker_url: str, timeout_seconds: float = 0.5) -> None:
        # Imported lazily so redis is only touched when this inspector is actually built.
        import redis

        # Bounded timeouts keep this off the critical path: a hung broker degrades to an error
        # (→ QueueProbeError) rather than blocking the request thread. Mirrors RedisCache's posture.
        self._redis = redis.Redis.from_url(
            broker_url,
            decode_responses=True,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        self._error = redis.RedisError  # base class we swallow / convert to QueueProbeError
        self._app = app
        self._timeout = timeout_seconds

    def snapshot(self) -> RawQueueSnapshot:
        queues = self._queue_depths()
        worker_count, active_count = self._worker_stats()
        return RawQueueSnapshot(queues=queues, worker_count=worker_count, active_count=active_count)

    def _queue_depths(self) -> list[QueueDepth]:
        try:
            # llen on the sync client returns an int; redis-py types it as a sync/async union, so
            # cast rather than int() (which the stubs reject for the Awaitable arm).
            return [
                QueueDepth(name=name, depth=cast("int", self._redis.llen(name)))
                for name in QUEUE_NAMES
            ]
        except self._error as exc:
            raise QueueProbeError(str(exc)) from exc

    def _worker_stats(self) -> tuple[int | None, int | None]:
        try:
            insp = self._app.control.inspect(timeout=self._timeout)
            # ping() -> {worker: {"ok": "pong"}}; active() -> {worker: [task, ...]}; both None when
            # no worker replies. `or {}` collapses that to an empty mapping.
            ping = insp.ping() or {}
            active = insp.active() or {}
        except Exception as exc:  # broad on purpose: kombu/redis/celery raise assorted types here
            _logger.warning("queue_inspect_unavailable", error=str(exc))
            return None, None
        return len(ping), int(sum(len(tasks) for tasks in active.values()))


@lru_cache
def get_queue_inspector() -> QueueInspector:
    """Build the production inspector wired to the configured broker (overridden in tests).

    Cached as a process-wide singleton (like ``get_cache``/``get_celery``) so the admin page's
    poll reuses one Redis connection pool instead of opening a fresh one per request. The broker
    URL is process config, so the singleton never goes stale within a run.
    """
    settings = get_settings()
    return CeleryQueueInspector(get_celery(), broker_url=settings.celery_broker_url)
