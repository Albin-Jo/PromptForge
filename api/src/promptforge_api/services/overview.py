"""Fleet-overview use-case: assemble the landing page's view from four read-models.

Composes registry rows, per-prompt traffic, latest eval quality, and latest scan risk into one
:class:`FleetOverview` — totals + a gap-filled trend + a per-prompt rollup carrying the "needs
attention" rule keys. The rules live here (one place, documented) rather than smeared across the UI;
the router maps the result to DTOs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from promptforge_api.repositories.metrics import MetricsBlock, MetricsBucket, MetricsRepository
from promptforge_api.repositories.overview import OverviewRepository, PromptRow, TrafficRow
from promptforge_api.services.metrics import WINDOWS, quality_from_summary, resolve_interval

# --- "needs attention" thresholds (kept here, named, so the rules read as policy not magic) -------
# Error rate above this over the window is worth a look (5%). A rate, not a count, so a low-traffic
# prompt with one error doesn't dominate — though see the rule for how tiny samples are handled.
HIGH_ERROR_RATE = 0.05
# A latest-version eval mean below this reads as "failing" rather than merely "evaluated".
LOW_QUALITY = 0.5
# Risk levels from a completed scan that warrant attention (mirrors the promotion gate's view).
RISKY_SCAN_LEVELS = frozenset({"high"})

# The attention rule keys the UI renders as badges. Stable strings (not prose) so the front end owns
# the wording; documented inline at each rule below.
ATTENTION_HIGH_ERROR = "high_error_rate"
ATTENTION_EVAL = "failing_or_missing_eval"
ATTENTION_SCAN = "unscanned_or_risky"
ATTENTION_IDLE = "no_recent_traffic"


@dataclass(frozen=True)
class PromptRollup:
    """One prompt's line in the fleet table: window traffic + latest quality + which rules fired."""

    name: str
    latest_version: int | None
    request_count: int
    error_rate: float | None
    p95_ms: float | None
    cost_usd: Decimal | None
    quality: float | None
    attention: list[str]


@dataclass(frozen=True)
class FleetOverview:
    """The whole landing page: window echo, fleet totals, a trend, and the per-prompt rollup."""

    window: str
    interval: str
    since: datetime
    totals: MetricsBlock
    trend: list[MetricsBucket]
    prompts: list[PromptRollup]


class OverviewService:
    """Composes the four read-models into the fleet view and applies the attention rules."""

    def __init__(self, metrics: MetricsRepository, overview: OverviewRepository) -> None:
        self._metrics = metrics
        self._overview = overview

    def fleet_overview(self, *, window: str, interval: str | None = None) -> FleetOverview:
        bucket_size = resolve_interval(window, interval)
        since = datetime.now(UTC) - WINDOWS[window]

        # Fleet totals + trend reuse the per-prompt read-model with no prompt filter (None = all).
        # "All" here is deliberately fleet-wide: it includes traffic with no prompt link (ad-hoc
        # gateway/playground calls), which the per-prompt rollup below cannot attribute to a row.
        # So ``totals``/``trend`` can exceed the sum of the rows by exactly that unlinked traffic —
        # that's intended (the headline is total platform spend/traffic, not just saved prompts);
        # see test_fleet_totals_include_unlinked_traffic. The UI labels this on the overview header.
        totals = self._metrics.overall(None, since)
        trend = self._metrics.timeseries(None, since, bucket_size)

        # Batched cross-prompt facts, then stitched per prompt (no query-per-prompt).
        rows = self._overview.prompt_rows()
        traffic = self._overview.traffic_by_prompt(since)
        version_ids = [r.latest_version_id for r in rows if r.latest_version_id is not None]
        eval_summaries = self._metrics.latest_eval_summary_by_version(version_ids)
        scan_risk = self._overview.latest_scan_risk_by_version(version_ids)

        prompts = [self._rollup(row, traffic, eval_summaries, scan_risk) for row in rows]

        return FleetOverview(
            window=window,
            interval=bucket_size,
            since=since,
            totals=totals,
            trend=trend,
            prompts=prompts,
        )

    def _rollup(
        self,
        row: PromptRow,
        traffic: dict[uuid.UUID, TrafficRow],
        eval_summaries: dict[uuid.UUID, dict[str, Any]],
        scan_risk: dict[uuid.UUID, str | None],
    ) -> PromptRollup:
        t = traffic.get(row.prompt_id)
        request_count = t.request_count if t else 0
        error_count = t.error_count if t else 0
        error_rate = (error_count / request_count) if request_count else None

        version_id = row.latest_version_id
        quality = quality_from_summary(eval_summaries.get(version_id)) if version_id else None

        return PromptRollup(
            name=row.name,
            latest_version=row.latest_version_number,
            request_count=request_count,
            error_rate=error_rate,
            p95_ms=t.p95_ms if t else None,
            cost_usd=t.cost_usd if t else None,
            quality=quality,
            attention=self._attention(
                row=row,
                request_count=request_count,
                error_rate=error_rate,
                quality=quality,
                has_eval=(version_id is not None and version_id in eval_summaries),
                scan_present=(version_id is not None and version_id in scan_risk),
                scan_risk=scan_risk.get(version_id) if version_id else None,
            ),
        )

    @staticmethod
    def _attention(
        *,
        row: PromptRow,
        request_count: int,
        error_rate: float | None,
        quality: float | None,
        has_eval: bool,
        scan_present: bool,
        scan_risk: str | None,
    ) -> list[str]:
        """Apply the (documented) 'needs attention' rules; return the keys that fired, in order.

        Four rules, deliberately simple and independent (sprint 16c keeps these legible):
        1. **high_error_rate** — the window's error rate is above HIGH_ERROR_RATE.
        2. **failing_or_missing_eval** — the latest version has no completed eval, or its quality is
           below LOW_QUALITY. Only meaningful once a version exists.
        3. **unscanned_or_risky** — the latest version was never scanned (completed), or its scan
           risk is in RISKY_SCAN_LEVELS. Only meaningful once a version exists.
        4. **no_recent_traffic** — an *established* prompt (more than one version) saw zero requests
           in the window: a possible dead/abandoned prompt. New one-version prompts don't trip it.
        """
        has_version = row.latest_version_id is not None
        flags: list[str] = []

        if error_rate is not None and error_rate > HIGH_ERROR_RATE:
            flags.append(ATTENTION_HIGH_ERROR)

        if has_version and (not has_eval or (quality is not None and quality < LOW_QUALITY)):
            flags.append(ATTENTION_EVAL)

        if has_version and (not scan_present or scan_risk in RISKY_SCAN_LEVELS):
            flags.append(ATTENTION_SCAN)

        if row.version_count > 1 and request_count == 0:
            flags.append(ATTENTION_IDLE)

        return flags
