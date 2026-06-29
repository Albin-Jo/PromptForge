"""Metrics use-case: assemble a prompt's observability picture from two read-models.

The four DoD numbers — p95 latency, total spend, error rate, and quality trend — don't live in one
table. Latency/cost/errors come from ``traces`` (the :class:`MetricsRepository`); quality comes
from ``eval_runs.summary``. This service is where the two are stitched together: resolve the prompt
name, turn the requested window into a ``since`` cutoff, gather the trace aggregates, then attach
each version's latest eval quality. Routers get one composed :class:`PromptMetrics`; persistence and
the eval-summary shape never leak past here (CLAUDE.md layering).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from promptforge_api.exceptions import PromptNotFoundError, VersionNotFoundError
from promptforge_api.repositories.metrics import (
    MetricsBlock,
    MetricsBucket,
    MetricsRepository,
    SourceCost,
    VersionMetrics,
)
from promptforge_api.repositories.prompts import PromptRepository

# The allowed query windows → how far back ``since`` reaches. A small fixed set (not a free-form
# range) keeps the surface tiny and the input trivially validated; arbitrary ranges are a later
# need, not a v0.1 one. Keep these keys in sync with the router's ``MetricsWindow`` literal.
WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# The bucket sizes the time-series endpoint can group by. Kept tiny and closed so the value is safe
# to inline into the ``date_trunc`` / ``generate_series`` SQL. Keep in sync with the router's
# ``MetricsInterval`` literal.
INTERVALS: frozenset[str] = frozenset({"hour", "day"})

# The sensible bucket size for each window when the caller doesn't pin one: fine-grained for a day,
# daily for the longer windows so cardinality stays low (24 / 7 / 30 buckets) — a fleet view should
# inform, not bury the trend under noise.
DEFAULT_INTERVAL: dict[str, str] = {"24h": "hour", "7d": "day", "30d": "day"}


def resolve_interval(window: str, interval: str | None) -> str:
    """Resolve the bucket size for a window (defaulting from it) and validate against ``INTERVALS``.

    The result is inlined into SQL (``date_trunc`` / ``generate_series``) by the repository, so this
    closed-set check is the *real* guard against an unexpected value reaching the query — not just
    the router's ``MetricsInterval`` literal, which only covers the HTTP path. Any non-HTTP caller
    (SDK, internal job, test) is validated here too. Raises ``ValueError`` on an unknown interval.
    """
    bucket_size = interval or DEFAULT_INTERVAL[window]
    if bucket_size not in INTERVALS:
        raise ValueError(f"unknown interval {interval!r}; expected one of {sorted(INTERVALS)}")
    return bucket_size


@dataclass(frozen=True)
class PromptMetrics:
    """A prompt's full metrics view over a window: overall, per version, and per feature."""

    name: str
    prompt_id: uuid.UUID
    window: str
    since: datetime
    overall: MetricsBlock
    by_version: list[VersionMetrics]
    by_source: list[SourceCost]


@dataclass(frozen=True)
class PromptTimeseries:
    """A prompt's metrics bucketed over time: one entry per ``interval`` bucket over the window.

    ``version`` is the version number the series was scoped to, or ``None`` for the whole prompt
    (every version combined) — the per-version form drives the dashboard's per-version sparklines.
    """

    name: str
    prompt_id: uuid.UUID
    window: str
    interval: str
    since: datetime
    version: int | None
    buckets: list[MetricsBucket]


class MetricsService:
    """Composes the trace read-model with per-version eval quality into one view."""

    def __init__(self, prompts: PromptRepository, metrics: MetricsRepository) -> None:
        self._prompts = prompts
        self._metrics = metrics

    def prompt_metrics(self, *, name: str, window: str) -> PromptMetrics:
        """Build the metrics view for *name* over *window*, or raise if the prompt is unknown."""
        prompt = self._prompts.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)

        since = datetime.now(UTC) - WINDOWS[window]
        overall = self._metrics.overall(prompt.id, since)
        versions = self._metrics.by_version(prompt.id, since)
        by_source = self._metrics.cost_by_source(prompt.id, since)

        # Attach each version's latest eval quality (one batched lookup, not one query per version).
        summaries = self._metrics.latest_eval_summary_by_version(
            [v.prompt_version_id for v in versions]
        )
        versions = [
            replace(v, quality=quality_from_summary(summaries.get(v.prompt_version_id)))
            for v in versions
        ]

        return PromptMetrics(
            name=name,
            prompt_id=prompt.id,
            window=window,
            since=since,
            overall=overall,
            by_version=versions,
            by_source=by_source,
        )

    def prompt_timeseries(
        self, *, name: str, window: str, interval: str | None = None, version: int | None = None
    ) -> PromptTimeseries:
        """Build the time-bucketed view for *name*, gap-filled and with quality stitched per bucket.

        ``interval`` defaults to a sensible size for the window (hourly for 24h, daily otherwise).
        ``version`` scopes the series to one version (the per-version sparklines); ``None`` is the
        whole prompt. Quality isn't a trace property, so it comes from a separate eval-run-by-bucket
        lookup and is joined onto the (gap-filled) trace spine here — same split as
        :meth:`prompt_metrics`, and version-scoped in lockstep when a version is given.
        """
        prompt = self._prompts.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)

        version_id: uuid.UUID | None = None
        if version is not None:
            match = next((v for v in prompt.versions if v.version_number == version), None)
            if match is None:
                raise VersionNotFoundError(name, version)
            version_id = match.id

        bucket_size = resolve_interval(window, interval)
        since = datetime.now(UTC) - WINDOWS[window]

        buckets = self._metrics.timeseries(prompt.id, since, bucket_size, version_id)
        quality_by_bucket = self._metrics.eval_quality_buckets(
            prompt.id, since, bucket_size, version_id
        )
        buckets = [
            replace(b, quality=_bucket_quality(quality_by_bucket.get(b.bucket_start)))
            for b in buckets
        ]

        return PromptTimeseries(
            name=name,
            prompt_id=prompt.id,
            window=window,
            interval=bucket_size,
            since=since,
            version=version,
            buckets=buckets,
        )


def _bucket_quality(summaries: list[dict[str, Any]] | None) -> float | None:
    """One quality number for a time bucket: the mean of each completed run's quality in it.

    Each summary is reduced by :func:`quality_from_summary` (mean of its scorers' means); runs with
    no usable mean are dropped. ``None`` when the bucket had no run with a quality — keeping
    "not evaluated this bucket" distinct from "scored 0", exactly as the per-version view does.
    """
    if not summaries:
        return None
    qualities = [q for q in (quality_from_summary(s) for s in summaries) if q is not None]
    return sum(qualities) / len(qualities) if qualities else None


def quality_from_summary(summary: dict[str, Any] | None) -> float | None:
    """Reduce an eval-run summary to a single quality number: the mean of its scorers' means.

    A run may grade with several scorers (judge + a RAGAS metric); each contributes a
    ``mean_value`` in [0,1] and we average them for one comparable figure. ``None`` when there's
    no summary or no scorer produced a mean (so "not evaluated" stays distinct from "scored 0").

    This is deliberately lossy: averaging semantically different scorers (a judge's intrinsic
    rating and a RAGAS factual-correctness metric) blurs them into one trend line. It's the right
    shape for an at-a-glance "is quality moving?", but per-scorer thresholds — the basis for a real
    pass/fail gate — are Sprint 11's job, not this view's.
    """
    if not summary:
        return None
    scorers = summary.get("scorers") or {}
    means = [
        s["mean_value"]
        for s in scorers.values()
        if isinstance(s, dict) and s.get("mean_value") is not None
    ]
    return sum(means) / len(means) if means else None
