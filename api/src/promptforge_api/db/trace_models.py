"""ORM model for the observability trace — the record of *what happened on every execution*.

Where the registry records what a prompt *is* and the eval tables record how *good* it is, a
:class:`Trace` records each *execution*: one model call, linked back to the exact prompt version
that produced it, with its tokens, computed cost, latency, and outcome. That linkage is the whole
point — it lets cost/latency/quality be sliced per prompt and per version over time (Phase 7).

This sprint only *defines and persists* the model + a config-driven pricing table; the gateway/SDK
**emitting** traces and Celery **ingesting** them asynchronously is Sprint 9 (so tracing never
slows the hot path). A flat trace per execution for v0.1 — the build plan's optional ``Span`` (for
multi-step calls) is deferred until there's multi-step work to trace (composition, Phase 9).

Persistence entity, not an API DTO (CLAUDE.md). The ``traces`` table is the first with a
*time-series* shape (append-heavy, queried by recent window); v0.1 indexes ``created_at`` and
leaves partitioning as the documented scaling lever (learning-backlog).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base


class Trace(Base):
    """One execution: the prompt version that ran, its tokens/cost/latency, and its outcome."""

    __tablename__ = "traces"
    __table_args__ = (
        # A trace either succeeded or failed; a CHECK keeps an invented status out of the data
        # of record (the same discipline as eval_runs.status).
        CheckConstraint("status IN ('ok', 'error')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # --- linkage: which prompt/version produced this execution -------------------------------
    # Denormalised prompt_id alongside the version FK so per-prompt cost attribution is a direct
    # filter, not a join, on a table that grows fast. Both nullable + SET NULL: a raw gateway
    # call may belong to no registered prompt, and a trace must survive the prompt/version being
    # deleted (the historical spend is the point of keeping it).
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL"), default=None, index=True
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None, index=True
    )
    # The correlation id threaded through logs + Celery (RequestIDMiddleware). Indexed so a trace
    # can be joined to the exact request's log lines. Nullable: not every emitter has one.
    request_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    # Where the call originated (sdk | playground | eval). Enables cost attribution *per feature*,
    # not just per model (build plan, Tier 2.4). Free-form on purpose; sources will grow.
    source: Mapped[str | None] = mapped_column(String(32), default=None)

    # --- the call ----------------------------------------------------------------------------
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    # The model requested; provider_model is what the provider actually served (may be more
    # specific), mirroring the gateway's Completion.model.
    model: Mapped[str] = mapped_column(String(255))
    provider_model: Mapped[str | None] = mapped_column(String(255), default=None)
    # The rendered prompt and the model output. Nullable so an emitter can omit them (size/PII);
    # kept by default so the Phase 12 trace view can show what actually ran.
    input: Mapped[str | None] = mapped_column(Text, default=None)
    output: Mapped[str | None] = mapped_column(Text, default=None)

    # --- accounting --------------------------------------------------------------------------
    # Token counts as the provider reported them; nullable because not every provider returns
    # usage. total is stored (not derived) since a provider may report it directly.
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    total_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # Computed cost = tokens × price (pricing.py). Numeric, not float — money rounds exactly.
    # NULL when tokens are unknown or the model is unpriced (honestly absent, never guessed at 0).
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    # --- outcome -----------------------------------------------------------------------------
    status: Mapped[str] = mapped_column(String(16))
    error_type: Mapped[str | None] = mapped_column(String(255), default=None)

    # Indexed: the trace table is queried by recent time window ("last 24h"), and this is the
    # column that scopes it. The first time-series index in the schema (learning-backlog).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
