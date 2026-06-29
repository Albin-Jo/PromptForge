"""The API's Celery *producer* client.

The API enqueues background work but never executes it. To stay decoupled from the
worker package (Decision B, Sprint 6 ADR), it submits tasks **by name** through this
thin client rather than importing ``promptforge_worker`` and calling the task object.

The trade-off of by-name submission is that the task name is a bare string shared
between the two packages. We make it explicit: the constants below mirror those in
``promptforge_worker.tasks`` and are the producer half of that contract — keep them in
sync. Serialization config here must also match the worker's, or messages won't decode.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

import structlog
from celery import Celery
from celery.result import AsyncResult
from celery.signals import before_task_publish

from promptforge_api.config import get_settings

# Producer half of the producer/consumer name contract. Mirrors the constants in
# promptforge_worker.tasks — keep in sync.
PING_TASK = "promptforge.health.ping"
RUN_EVAL_TASK = "promptforge.eval.run"
RUN_SCAN_TASK = "promptforge.scan.run"
TRACE_INGEST_TASK = "promptforge.trace.ingest"
DELIVER_WEBHOOK_TASK = "promptforge.webhook.deliver"

# A gating eval is enqueued *before* the request transaction that created its run row commits
# (the API commits in its dependency teardown, after the handler returns). A short countdown
# means the worker won't pick the task up until that commit has landed, so run_eval never sees
# a not-yet-visible row. Pragmatic guard for v0.1; the principled fix is a transactional outbox.
_EVAL_ENQUEUE_COUNTDOWN_SECONDS = 2

# Header name under which the correlation id rides with the task. The worker's
# task_prerun handler reads it back off task.request (must match that name).
REQUEST_ID_HEADER = "request_id"


@before_task_publish.connect
def inject_request_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    """Stamp the current request's correlation id onto the outgoing task's headers.

    Runs in the producer (the API process) at enqueue time. RequestIDMiddleware binds
    ``request_id`` to structlog's contextvars per request; we copy it into the task
    headers so the worker can re-bind it and the job's logs trace back to the request.
    """
    if headers is None:
        return
    request_id = structlog.contextvars.get_contextvars().get(REQUEST_ID_HEADER)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id


@lru_cache
def get_celery() -> Celery:
    """Return the process-wide producer Celery app, configured to match the worker."""
    settings = get_settings()
    app = Celery(
        "promptforge-api-producer",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    # Must match promptforge_worker.celery_app: JSON-only, or the worker rejects the
    # message (and the API can't decode results).
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Routing is applied by the PUBLISHER, so the producer needs the route map too —
        # the worker's copy alone won't place a message on the right queue. Mirrors
        # promptforge_worker.celery_app's task_routes; keep the two in sync.
        task_routes={
            "promptforge.eval.*": {"queue": "evals"},
            "promptforge.scan.*": {"queue": "scans"},
            "promptforge.trace.*": {"queue": "traces"},
        },
    )
    return app


def enqueue(task_name: str, *args: object, **kwargs: object) -> AsyncResult:
    """Submit *task_name* to the broker and return its handle (carrying the job id)."""
    return get_celery().send_task(task_name, args=args, kwargs=kwargs)


def enqueue_eval(eval_run_id: uuid.UUID) -> AsyncResult:
    """Enqueue a gating eval, delayed slightly so the run row is committed before it runs."""
    return get_celery().send_task(
        RUN_EVAL_TASK,
        kwargs={"eval_run_id": str(eval_run_id)},
        countdown=_EVAL_ENQUEUE_COUNTDOWN_SECONDS,
    )


def enqueue_scan(security_scan_id: uuid.UUID) -> AsyncResult:
    """Enqueue a security scan, delayed slightly so the scan row is committed before it runs.

    Same race as the eval enqueue (the row commits in the request's dependency teardown, after the
    handler returns), so we reuse the same short countdown — the worker won't pick the scan up
    until the not-yet-visible row has landed.
    """
    return get_celery().send_task(
        RUN_SCAN_TASK,
        kwargs={"security_scan_id": str(security_scan_id)},
        countdown=_EVAL_ENQUEUE_COUNTDOWN_SECONDS,
    )


def enqueue_webhook(payload: dict[str, Any], *, url: str, secret: str | None) -> AsyncResult:
    """Enqueue delivery of one promotion event to a subscriber URL (off the request path)."""
    return get_celery().send_task(
        DELIVER_WEBHOOK_TASK,
        kwargs={"payload": payload, "url": url, "secret": secret},
    )
