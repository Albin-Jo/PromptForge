"""Read-model for observability metrics — aggregation queries over traces (+ eval quality).

This is the *read* side of Phase 7: the write path (``observability.persist_trace``) appends one
row per execution; this turns a window of those rows into the numbers a dashboard asks for —
latency percentiles, error rate, and cost — sliced overall, per version, and per feature (source).

**Aggregation runs in Postgres, not Python.** Latency percentiles use the ordered-set aggregate
``percentile_cont(p) WITHIN GROUP (ORDER BY latency_ms)`` so the database computes them in place
over the indexed ``created_at`` window, returning a few floats — never streaming every row back to
compute a percentile client-side. ``percentile_cont`` *interpolates* (a p95 may fall between two
observed latencies), which is the right choice for a latency SLO; ``percentile_disc`` (an actual
observed value) is the alternative we didn't need. NULLs are ignored by these aggregates, so a
trace with no reported latency/cost simply doesn't count rather than skewing the result to 0.

The value objects below are this read-model's own result types (frozen, Pydantic-free): the
service composes them and the router maps them to DTOs, so persistence shapes never reach the edge.
Quality lives in a different table (``eval_runs.summary``), so it's fetched separately here and
stitched on by the service — these metrics deliberately span two subsystems (traces + evals).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.models import PromptVersion
from promptforge_api.db.trace_models import Trace


@dataclass(frozen=True)
class LatencyPercentiles:
    """Latency distribution in ms; each is ``None`` when no trace in the window reported one."""

    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


@dataclass(frozen=True)
class MetricsBlock:
    """The core aggregate over a set of traces: volume, errors, latency, and spend."""

    request_count: int
    error_count: int
    # errors / requests, or None when there were no requests (no faked 0 over an empty window).
    error_rate: float | None
    latency: LatencyPercentiles
    # Summed cost; None when nothing in the set had a known cost (unpriced/no usage).
    total_cost_usd: Decimal | None


@dataclass(frozen=True)
class VersionMetrics:
    """One version's metrics. ``quality`` is filled by the service from the eval read-model."""

    version_number: int
    prompt_version_id: uuid.UUID
    metrics: MetricsBlock
    quality: float | None


@dataclass(frozen=True)
class SourceCost:
    """Spend attributed to one feature/source (``sdk`` / ``playground`` / ``eval`` / unset)."""

    source: str | None
    cost_usd: Decimal | None


@dataclass(frozen=True)
class MetricsBucket:
    """One time bucket of the series — the same aggregates as :class:`MetricsBlock`, sliced by time.

    Empty buckets survive gap-fill: ``request_count`` is a real ``0`` while the rates/latency/cost/
    quality stay ``None`` — "no traffic in this bucket" must read differently from "zero cost". The
    repo leaves ``quality`` ``None``; the service fills it from the eval read-model (it isn't a
    trace property — see :meth:`MetricsRepository.eval_quality_buckets`).
    """

    bucket_start: datetime
    request_count: int
    error_rate: float | None
    p95_ms: float | None
    cost_usd: Decimal | None
    quality: float | None


def _block(
    n: int,
    errors: int,
    p50: float | None,
    p95: float | None,
    p99: float | None,
    cost: Decimal | None,
) -> MetricsBlock:
    """Assemble a :class:`MetricsBlock`, deriving error_rate (None over an empty set)."""
    return MetricsBlock(
        request_count=n,
        error_count=errors,
        error_rate=(errors / n if n else None),
        latency=LatencyPercentiles(p50_ms=p50, p95_ms=p95, p99_ms=p99),
        total_cost_usd=cost,
    )


class MetricsRepository:
    """Aggregation queries over the ``traces`` window, plus the per-version eval-quality lookup."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _aggregates(self) -> tuple[Any, ...]:
        """The shared SELECT list: count, error count, the three percentiles, and summed cost.

        Defined once so ``overall`` and ``by_version`` compute identical metrics — the only
        difference between them is the GROUP BY, never the aggregate definitions.
        """
        return (
            func.count(),
            func.count().filter(Trace.status == "error"),
            func.percentile_cont(0.5).within_group(Trace.latency_ms.asc()),
            func.percentile_cont(0.95).within_group(Trace.latency_ms.asc()),
            func.percentile_cont(0.99).within_group(Trace.latency_ms.asc()),
            func.sum(Trace.cost_usd),
        )

    def overall(self, prompt_id: uuid.UUID | None, since: datetime) -> MetricsBlock:
        """Metrics across traces in the window. ``prompt_id`` scopes to one prompt; ``None`` is
        fleet-wide (every trace), which the overview uses for its totals."""
        conditions = [Trace.created_at >= since]
        if prompt_id is not None:
            conditions.append(Trace.prompt_id == prompt_id)
        row = self._session.execute(select(*self._aggregates()).where(*conditions)).one()
        return _block(*row)

    def by_version(self, prompt_id: uuid.UUID, since: datetime) -> list[VersionMetrics]:
        """The same metrics grouped by the version that produced them, oldest version first.

        Only version-linked traces (an inner join to ``prompt_versions``) — a raw, version-less
        call can't be attributed to a version, so it's in ``overall`` but not here. ``quality`` is
        left ``None`` for the service to fill from the eval read-model.
        """
        rows = self._session.execute(
            select(PromptVersion.version_number, PromptVersion.id, *self._aggregates())
            .join(PromptVersion, Trace.prompt_version_id == PromptVersion.id)
            .where(Trace.prompt_id == prompt_id, Trace.created_at >= since)
            .group_by(PromptVersion.id, PromptVersion.version_number)
            .order_by(PromptVersion.version_number)
        ).all()
        return [
            VersionMetrics(
                version_number=version_number,
                prompt_version_id=version_id,
                metrics=_block(n, errors, p50, p95, p99, cost),
                quality=None,
            )
            for version_number, version_id, n, errors, p50, p95, p99, cost in rows
        ]

    def cost_by_source(self, prompt_id: uuid.UUID, since: datetime) -> list[SourceCost]:
        """Total spend grouped by feature/source — the 'cost attribution per feature' slice."""
        rows = self._session.execute(
            select(Trace.source, func.sum(Trace.cost_usd))
            .where(Trace.prompt_id == prompt_id, Trace.created_at >= since)
            .group_by(Trace.source)
            .order_by(Trace.source)
        ).all()
        return [SourceCost(source=source, cost_usd=cost) for source, cost in rows]

    def latest_eval_summary_by_version(
        self, version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """The most recent *completed* eval run's summary per version (``DISTINCT ON``).

        Not window-scoped: quality is a property of the version itself ("how good is v3?"), so we
        take its latest verdict regardless of when traffic happened. Versions never evaluated, or
        whose latest run has no summary, are simply absent from the map.
        """
        if not version_ids:
            return {}
        rows = self._session.execute(
            select(EvalRun.prompt_version_id, EvalRun.summary)
            .where(
                EvalRun.prompt_version_id.in_(version_ids),
                EvalRun.status == "completed",
                # Defend the ORDER BY below: Postgres sorts NULLs *first* under DESC, so a
                # completed run with no timestamp would be picked as "latest" over a real one.
                # The invariant (completed ⇒ completed_at set) holds today; this stops a future
                # code path that breaks it from silently corrupting every quality number.
                EvalRun.completed_at.is_not(None),
            )
            # DISTINCT ON keeps the first row per version under the ORDER BY, so ordering by
            # completed_at DESC within each version yields each version's latest completed run.
            .distinct(EvalRun.prompt_version_id)
            .order_by(EvalRun.prompt_version_id, EvalRun.completed_at.desc())
        ).all()
        return {version_id: summary for version_id, summary in rows if summary is not None}

    def timeseries(
        self,
        prompt_id: uuid.UUID | None,
        since: datetime,
        interval: str,
        prompt_version_id: uuid.UUID | None = None,
    ) -> list[MetricsBucket]:
        """The trace aggregates bucketed over time, **gap-filled** so empty buckets are present.

        ``interval`` is a trusted, closed value (``'hour'`` / ``'day'`` — validated at the service
        boundary, never user free-form), so it can be inlined into the ``generate_series`` step.

        The shape is a left join of a *complete* bucket spine onto the actual per-bucket aggregates:

        * ``buckets`` — ``generate_series`` from the truncated ``since`` to the truncated *now*,
          stepping one interval, produces **every** boundary in range, even ones with no traffic.
        * ``agg`` — the same percentile/count/sum aggregates as :meth:`overall`, but ``GROUP BY``
          the ``date_trunc`` of ``created_at`` (so each row is one bucket's numbers).
        * the outer ``LEFT JOIN`` keeps every spine bucket; ``COALESCE`` turns a missing match into
          a real ``0`` request count, while latency/cost stay ``NULL`` (honestly absent, not 0).

        Both the spine and ``agg`` truncate with the *same* ``date_trunc(interval, …)``, so the join
        keys line up exactly regardless of the database's session timezone.
        """
        # Inline the (closed-set, trusted) interval as a SQL literal rather than a bound parameter:
        # Postgres must see the SELECT and GROUP BY ``date_trunc`` as the *same* expression, and two
        # different bind placeholders for the same value defeat that ("must appear in GROUP BY").
        unit = text(f"'{interval}'")
        step = text(f"interval '1 {interval}'")
        buckets = select(
            func.generate_series(
                func.date_trunc(unit, since),
                func.date_trunc(unit, func.now()),
                step,
            ).label("bucket_start")
        ).cte("buckets")

        bucket_expr = func.date_trunc(unit, Trace.created_at)
        conditions = [Trace.created_at >= since]
        if prompt_id is not None:  # None → fleet-wide (the overview's trend)
            conditions.append(Trace.prompt_id == prompt_id)
        if prompt_version_id is not None:  # scope to one version (per-version sparklines)
            conditions.append(Trace.prompt_version_id == prompt_version_id)
        agg = (
            select(
                bucket_expr.label("bucket_start"),
                func.count().label("n"),
                func.count().filter(Trace.status == "error").label("errors"),
                func.percentile_cont(0.95).within_group(Trace.latency_ms.asc()).label("p95"),
                func.sum(Trace.cost_usd).label("cost"),
            )
            .where(*conditions)
            .group_by(bucket_expr)
            .cte("agg")
        )

        rows = self._session.execute(
            select(
                buckets.c.bucket_start,
                func.coalesce(agg.c.n, 0),
                func.coalesce(agg.c.errors, 0),
                agg.c.p95,
                agg.c.cost,
            )
            .select_from(buckets.outerjoin(agg, agg.c.bucket_start == buckets.c.bucket_start))
            .order_by(buckets.c.bucket_start)
        ).all()

        return [
            MetricsBucket(
                bucket_start=bucket_start,
                request_count=n,
                error_rate=(errors / n if n else None),
                p95_ms=p95,
                cost_usd=cost,
                quality=None,  # filled by the service from eval_quality_buckets
            )
            for bucket_start, n, errors, p95, cost in rows
        ]

    def eval_quality_buckets(
        self,
        prompt_id: uuid.UUID,
        since: datetime,
        interval: str,
        prompt_version_id: uuid.UUID | None = None,
    ) -> dict[datetime, list[dict[str, Any]]]:
        """Completed eval-run summaries grouped by the bucket their ``completed_at`` falls in.

        Quality is **not** a trace property — it lives in ``eval_runs`` against a *version* — so it
        can't ride the trace aggregation. Instead each completed run is bucketed by the *same*
        ``date_trunc(interval, completed_at)`` the trace spine uses, so the returned keys line up
        with :meth:`timeseries`' ``bucket_start`` values exactly. The service reduces each bucket's
        summaries to one quality number (it owns the lossy scorer-mean reduction, ``_quality``).

        Runs are low-volume (evals are infrequent), so reducing in Python is cheap — the SQL only
        does the bucketing and the prompt/version join.
        """
        conditions = [
            PromptVersion.prompt_id == prompt_id,
            EvalRun.status == "completed",
            EvalRun.completed_at.is_not(None),
            EvalRun.completed_at >= since,
        ]
        if prompt_version_id is not None:  # scope quality to one version too (per-version series)
            conditions.append(EvalRun.prompt_version_id == prompt_version_id)
        rows = self._session.execute(
            select(
                func.date_trunc(text(f"'{interval}'"), EvalRun.completed_at).label("bucket_start"),
                EvalRun.summary,
            )
            .join(PromptVersion, EvalRun.prompt_version_id == PromptVersion.id)
            .where(*conditions)
        ).all()

        out: dict[datetime, list[dict[str, Any]]] = {}
        for bucket_start, summary in rows:
            if summary is not None:
                out.setdefault(bucket_start, []).append(summary)
        return out
