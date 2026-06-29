"""Tests for queue routing on the worker app.

Routing was only ever verified by hand (redis-cli LLEN). These pin it: the eval task must
land on the heavy `evals` queue and the ping on the default queue, so a future rename can't
silently misroute work. (The *publisher* applies routing, so the producer side is covered by
the API's celery contract test; this covers the worker app's own config.)
"""

from promptforge_worker.celery_app import DEFAULT_QUEUE, EVALS_QUEUE, TRACES_QUEUE, app
from promptforge_worker.tasks import PING_TASK, RUN_EVAL_TASK, TRACE_INGEST_TASK


def _routed_queue(task_name: str) -> str:
    route = app.amqp.router.route({}, task_name)
    queue = route["queue"]
    return str(getattr(queue, "name", queue))


def test_eval_task_routes_to_evals_queue() -> None:
    assert _routed_queue(RUN_EVAL_TASK) == EVALS_QUEUE


def test_ping_task_routes_to_default_queue() -> None:
    assert _routed_queue(PING_TASK) == DEFAULT_QUEUE


def test_trace_ingest_task_routes_to_traces_queue() -> None:
    # High-volume telemetry on its own queue, so a trace burst can't delay slow eval jobs.
    assert _routed_queue(TRACE_INGEST_TASK) == TRACES_QUEUE
