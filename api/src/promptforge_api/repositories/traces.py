"""Read access for observability traces — the list + single-trace lookups behind the UI's
debugging surface (Sprint 24, T3/T4).

Traces are *written* by the Celery worker (the ingest path on ``POST /traces`` enqueues; the
worker persists). This repository is the **read** half the UI needs: page a prompt's recent
executions, and fetch one execution in full. It is deliberately separate from
:class:`MetricsRepository`, which only ever *aggregates* the table — here we read individual rows.

The list defers the two heavy ``Text`` columns (``input`` / ``output``): the traces table is the
fastest-growing one in the schema, so the list must never drag a rendered prompt + model output
back for every row. Those load only on the single-trace ``get`` that the drill-down uses.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from promptforge_api.db.trace_models import Trace


class TraceRepository:
    """Read-only access to persisted traces: a paged list and a single full row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_traces(
        self,
        *,
        prompt_id: uuid.UUID | None,
        prompt_version_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> list[Trace]:
        """A page of traces, newest first, optionally scoped to a prompt and/or version.

        ``input``/``output`` are deferred — the list shows latency/cost/status/model only, so the
        heavy text columns never load here (they would dominate the row size on a hot table).
        """
        stmt = (
            select(Trace)
            .options(defer(Trace.input), defer(Trace.output))
            .order_by(Trace.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if prompt_id is not None:
            stmt = stmt.where(Trace.prompt_id == prompt_id)
        if prompt_version_id is not None:
            stmt = stmt.where(Trace.prompt_version_id == prompt_version_id)
        return list(self._session.scalars(stmt).all())

    def get(self, trace_id: uuid.UUID) -> Trace | None:
        """Fetch one trace in full (including the rendered ``input`` and ``output``)."""
        return self._session.get(Trace, trace_id)
