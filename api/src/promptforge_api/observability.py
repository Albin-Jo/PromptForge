"""The trace event and its persistence — the domain core of observability ingestion.

A :class:`TraceEvent` is one *emitted* execution: the Pydantic-free, JSON-serialisable
form of "this model call happened." It is the **producer/consumer contract** for the
trace-ingest queue — an emitter builds one and ships ``to_dict()`` as the Celery task's
payload; the worker rebuilds it with ``from_dict()`` and calls :func:`persist_trace`.

Keeping it a plain dataclass (not a Pydantic model) honours the boundary rule: the HTTP
edge validates with a Pydantic DTO (``schemas.TraceIngestRequest``) and converts to this;
the domain + worker never import Pydantic (CLAUDE.md / ADR 0003).

:func:`persist_trace` is where the token counts become money (via :mod:`pricing`) and a
``traces`` row is written. It is **idempotent on the trace id**: the emitter generates the
id, so a Celery redelivery (``acks_late``) of the same event inserts nothing the second
time — telemetry, but spend totals still must not double-count.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from promptforge_api.db.trace_models import Trace
from promptforge_api.pricing import cost_for

_logger = structlog.get_logger(__name__)

# The execution sources we attribute cost/latency to (the trace's ``source``). Free-form
# in the column on purpose (sources will grow), but these are the v0.1 emitters.
SOURCE_SDK = "sdk"
SOURCE_PLAYGROUND = "playground"
SOURCE_EVAL = "eval"

_VALID_STATUSES = frozenset({"ok", "error"})


@dataclass(frozen=True)
class TraceEvent:
    """One emitted execution, ready to persist. The queue message's typed form.

    Only ``model`` and ``status`` are required (you always know what you called and
    whether it worked). Everything else is optional because not every emitter has it:
    a raw playground call has no version link, a streamed call may have no token usage.
    ``id`` is generated here when absent so the same event is idempotent across redelivery.
    """

    model: str
    status: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    prompt_id: uuid.UUID | None = None
    prompt_version_id: uuid.UUID | None = None
    request_id: str | None = None
    source: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    input: str | None = None
    output: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            # Mirror the DB CHECK constraint, but fail at the boundary with a clear message
            # rather than as an opaque IntegrityError deep in the worker.
            raise ValueError(
                f"status must be one of {sorted(_VALID_STATUSES)}, got {self.status!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe payload for the Celery message (UUIDs as strings)."""
        data = asdict(self)
        data["id"] = str(self.id)
        data["prompt_id"] = str(self.prompt_id) if self.prompt_id is not None else None
        data["prompt_version_id"] = (
            str(self.prompt_version_id) if self.prompt_version_id is not None else None
        )
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceEvent:
        """Rebuild an event from a queue payload, parsing the id columns back to UUID.

        Tolerant of unknown keys (a newer emitter may add fields) so the consumer doesn't
        break on a forward-compatible message — extra keys are dropped, not fatal.
        """
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
        for key in ("id", "prompt_id", "prompt_version_id"):
            value = kwargs.get(key)
            if isinstance(value, str):
                kwargs[key] = uuid.UUID(value)
        return cls(**kwargs)


def persist_trace(session: Session, event: TraceEvent) -> None:
    """Compute cost and insert the trace, idempotently on its id.

    ``total_tokens`` is filled from input+output when the emitter didn't report it directly;
    ``cost_usd`` is ``None`` for an unpriced model or missing usage (honestly absent, never a
    guessed 0 — see :mod:`pricing`). The insert is ``ON CONFLICT (id) DO NOTHING`` so a
    redelivered event is a no-op rather than a duplicate row or an IntegrityError.
    """
    total_tokens = event.total_tokens
    if total_tokens is None and event.input_tokens is not None and event.output_tokens is not None:
        total_tokens = event.input_tokens + event.output_tokens

    cost_usd = cost_for(event.model, event.input_tokens, event.output_tokens)

    stmt = (
        pg_insert(Trace)
        .values(
            id=event.id,
            prompt_id=event.prompt_id,
            prompt_version_id=event.prompt_version_id,
            request_id=event.request_id,
            source=event.source,
            provider=event.provider,
            model=event.model,
            provider_model=event.provider_model,
            input=event.input,
            output=event.output,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            latency_ms=event.latency_ms,
            status=event.status,
            error_type=event.error_type,
        )
        # Idempotent on the emitter-generated primary key: a redelivered event writes nothing.
        # RETURNING id yields the row when inserted, nothing when the conflict skipped it —
        # which is how we tell a fresh ingest from a deduplicated redelivery.
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(Trace.id)
    )
    inserted = session.execute(stmt).scalar_one_or_none()
    if inserted is None:
        _logger.info("trace_ingest_duplicate_skipped", trace_id=str(event.id))
    else:
        _logger.info(
            "trace_ingested",
            trace_id=str(event.id),
            source=event.source,
            model=event.model,
            status=event.status,
            cost_usd=str(cost_usd) if cost_usd is not None else None,
        )
