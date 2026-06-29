"""HTTP layer for trace ingestion: the door an out-of-process emitter knocks on.

The SDK can't talk to Celery/Redis (it's a thin client another app imports), so it reports
an execution over HTTP here. This endpoint does the minimum on the request path — validate,
stamp the correlation id, enqueue — and returns ``202 Accepted`` immediately. The actual
DB write happens on the worker (``promptforge.trace.ingest``), so tracing never sits on the
caller's hot path (ADR 0013).

In-process emitters (the playground route, the eval runner) skip this endpoint and enqueue
the same task directly — they're already inside a process that has ``enqueue``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, status

from promptforge_api.celery_client import TRACE_INGEST_TASK, enqueue
from promptforge_api.observability import TraceEvent
from promptforge_api.schemas import TraceAccepted, TraceIngestRequest
from promptforge_api.security import require_api_key

router = APIRouter(prefix="/traces", tags=["traces"])
_logger = structlog.get_logger(__name__)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TraceAccepted,
    dependencies=[Depends(require_api_key)],
)
def ingest_trace(payload: TraceIngestRequest) -> TraceAccepted:
    """Accept one emitted execution and enqueue it for async persistence.

    Returns ``202`` (accepted, not yet stored): the trace is written by the worker. The
    response carries the ``trace_id`` so a client can correlate, and so a client that didn't
    supply an ``id`` learns the one the server minted.
    """
    # The trace's correlation id is the *request's* id (bound by RequestIDMiddleware), not a
    # client-supplied field — it ties the trace to this ingest request's log lines.
    data = payload.model_dump(mode="json", exclude_none=True)
    data["request_id"] = structlog.contextvars.get_contextvars().get("request_id")
    event = TraceEvent.from_dict(data)

    enqueue(TRACE_INGEST_TASK, payload=event.to_dict())
    _logger.info("trace_enqueued", trace_id=str(event.id), source=event.source)
    return TraceAccepted(trace_id=event.id)
