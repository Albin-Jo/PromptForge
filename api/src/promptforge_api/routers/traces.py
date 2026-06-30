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

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from promptforge_api.celery_client import TRACE_INGEST_TASK, enqueue
from promptforge_api.db.engine import get_session
from promptforge_api.db.trace_models import Trace
from promptforge_api.observability import TraceEvent
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.repositories.traces import TraceRepository
from promptforge_api.routers._mappers import money
from promptforge_api.schemas import (
    TraceAccepted,
    TraceDetail,
    TraceIngestRequest,
    TraceSummary,
)
from promptforge_api.security import require_api_key
from promptforge_api.services.traces import (
    DEFAULT_TRACE_PAGE_SIZE,
    MAX_TRACE_PAGE_SIZE,
    TraceService,
)

router = APIRouter(prefix="/traces", tags=["traces"])
_logger = structlog.get_logger(__name__)

SessionDep = Annotated[Session, Depends(get_session)]


def _trace_service(session: Session) -> TraceService:
    return TraceService(TraceRepository(session), PromptRepository(session))


def get_trace_service(session: SessionDep) -> TraceService:
    return _trace_service(session)


TraceServiceDep = Annotated[TraceService, Depends(get_trace_service)]


def _summary_dto(trace: Trace) -> TraceSummary:
    return TraceSummary(
        id=trace.id,
        prompt_id=trace.prompt_id,
        prompt_version_id=trace.prompt_version_id,
        source=trace.source,
        provider=trace.provider,
        model=trace.model,
        cost_usd=money(trace.cost_usd),
        latency_ms=trace.latency_ms,
        status=trace.status,
        created_at=trace.created_at,
    )


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


@router.get("", response_model=list[TraceSummary])
def list_traces(
    service: TraceServiceDep,
    prompt: str | None = None,
    version: int | None = None,
    limit: int = Query(DEFAULT_TRACE_PAGE_SIZE, ge=1, le=MAX_TRACE_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> list[TraceSummary]:
    """List executions, newest first — optionally scoped to a prompt and/or one of its versions.

    The lean list (no rendered prompt/output); the full execution is the single-trace detail.
    Unknown ``prompt``/``version`` → 404. ``version`` without ``prompt`` → 422.
    """
    if version is not None and prompt is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`version` requires `prompt`",
        )
    traces = service.list_traces(
        prompt_name=prompt, version_number=version, limit=limit, offset=offset
    )
    return [_summary_dto(t) for t in traces]


@router.get("/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: uuid.UUID, service: TraceServiceDep) -> TraceDetail:
    """Fetch one execution in full: the rendered prompt, the model output, and all its metadata."""
    trace = service.get_trace(trace_id)
    return TraceDetail(
        id=trace.id,
        prompt_id=trace.prompt_id,
        prompt_version_id=trace.prompt_version_id,
        source=trace.source,
        provider=trace.provider,
        model=trace.model,
        cost_usd=money(trace.cost_usd),
        latency_ms=trace.latency_ms,
        status=trace.status,
        created_at=trace.created_at,
        provider_model=trace.provider_model,
        request_id=trace.request_id,
        input=trace.input,
        output=trace.output,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        total_tokens=trace.total_tokens,
        error_type=trace.error_type,
    )
