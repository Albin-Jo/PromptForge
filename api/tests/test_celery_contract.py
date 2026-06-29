"""Contract tests pinning the API↔worker Celery agreement.

The API submits work by name (Decision B, ADR 0008): it imports no worker code at runtime,
so the task names, the routing map, and the correlation-id header are *mirrored* constants in
both packages. Mirroring drifts silently — rename a queue on one side and work misroutes with
no error. These tests import both packages (test-only) and assert the two halves still agree,
and that the producer's own routing + header injection behave.
"""

import structlog

from promptforge_api import celery_client
from promptforge_worker import signals as worker_signals
from promptforge_worker import tasks as worker_tasks
from promptforge_worker.celery_app import app as worker_app


def _routed_queue(app: object, task_name: str) -> str:
    route = app.amqp.router.route({}, task_name)  # type: ignore[attr-defined]
    queue = route["queue"]
    return str(getattr(queue, "name", queue))


def test_task_name_constants_match() -> None:
    assert celery_client.PING_TASK == worker_tasks.PING_TASK
    assert celery_client.RUN_EVAL_TASK == worker_tasks.RUN_EVAL_TASK
    assert celery_client.RUN_SCAN_TASK == worker_tasks.RUN_SCAN_TASK
    assert celery_client.TRACE_INGEST_TASK == worker_tasks.TRACE_INGEST_TASK
    assert celery_client.DELIVER_WEBHOOK_TASK == worker_tasks.DELIVER_WEBHOOK_TASK


def test_route_maps_match() -> None:
    # The producer must route to the same queues the worker declares, or work is misrouted.
    assert celery_client.get_celery().conf.task_routes == worker_app.conf.task_routes


def test_request_id_header_matches() -> None:
    # Producer injects under this header; worker reads it back. A mismatch breaks tracing.
    assert celery_client.REQUEST_ID_HEADER == worker_signals.REQUEST_ID_HEADER


def test_producer_routes_eval_to_evals_queue() -> None:
    # This is the bug class that bit during the build: routing lives on the *publisher*.
    assert _routed_queue(celery_client.get_celery(), celery_client.RUN_EVAL_TASK) == "evals"


def test_producer_routes_scan_to_scans_queue() -> None:
    # Same routing-on-the-publisher contract for the new scan task: it must land on `scans`.
    assert _routed_queue(celery_client.get_celery(), celery_client.RUN_SCAN_TASK) == "scans"


def test_inject_request_id_copies_bound_id_into_headers() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    headers: dict[str, object] = {}
    celery_client.inject_request_id(headers=headers)
    assert headers[celery_client.REQUEST_ID_HEADER] == "req-123"
    structlog.contextvars.clear_contextvars()


def test_inject_request_id_noop_without_bound_id() -> None:
    structlog.contextvars.clear_contextvars()
    headers: dict[str, object] = {}
    celery_client.inject_request_id(headers=headers)
    assert celery_client.REQUEST_ID_HEADER not in headers
