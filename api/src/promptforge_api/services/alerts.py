"""Drift / regression alerts — a pure policy layer over the metrics read-model (Phase 7).

Given a prompt's :class:`PromptMetrics` (task 3) and a threshold :class:`AlertPolicy` (from
config), :func:`evaluate_alerts` returns the breaches: quality below a floor, a version that
regressed against the one before it, an error rate too high, or cost per call too high.

This is **observational** alerting — "is the live data bad right now?" — surfaced via an endpoint
and a structured log. It is *not* promotion gating (Sprint 11) and it does not deliver or persist
alerts. The function is **pure** (no I/O): metrics in, alerts out, so it's exhaustively testable by
handing it fabricated metrics ("evaluate the evaluator").

Two deliberate asymmetries:
- The **min-requests floor** gates only the *traffic-derived* signals (error rate, cost), which go
  noisy on thin data. **Quality** is not gated by it — quality comes from a completed eval over a
  dataset, so it's already a deliberate, non-noisy sample.
- Because `by_version` is traces-driven (ADR 0014), quality alerts only cover versions with traffic
  in the window. That's the right scope for *observational* alerting (flag a degraded version while
  it's actually serving); catching a regression *before* it gets traffic is gating's job, not this.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from promptforge_api.config import Settings
from promptforge_api.repositories.metrics import MetricsBlock
from promptforge_api.services.metrics import PromptMetrics


@dataclass(frozen=True)
class AlertPolicy:
    """The thresholds an evaluation is judged against (built from :class:`Settings`)."""

    min_quality: float
    max_error_rate: float
    max_cost_per_request_usd: Decimal
    max_quality_drop: float
    min_requests: int

    @classmethod
    def from_settings(cls, settings: Settings) -> AlertPolicy:
        return cls(
            min_quality=settings.alert_min_quality,
            max_error_rate=settings.alert_max_error_rate,
            max_cost_per_request_usd=settings.alert_max_cost_per_request_usd,
            max_quality_drop=settings.alert_max_quality_drop,
            min_requests=settings.alert_min_requests,
        )


@dataclass(frozen=True)
class Alert:
    """One threshold breach. ``observed`` is the measured value, ``threshold`` the line it crossed.

    ``kind`` is a stable machine code; ``scope`` is ``"overall"`` or ``"version:<n>"``; ``message``
    is the human-readable summary. ``observed``/``threshold`` are floats for a uniform shape — for
    the cost signal they're dollar amounts (precise enough for an alert, not for accounting).
    """

    kind: str
    scope: str
    observed: float
    threshold: float
    message: str


def evaluate_alerts(metrics: PromptMetrics, policy: AlertPolicy) -> list[Alert]:
    """Return every threshold currently breached for *metrics* (empty when all is healthy)."""
    alerts: list[Alert] = []
    alerts.extend(_overall_alerts(metrics.overall, policy))
    alerts.extend(_quality_alerts(metrics, policy))
    return alerts


def _overall_alerts(overall: MetricsBlock, policy: AlertPolicy) -> list[Alert]:
    """Traffic-derived signals (error rate, cost/call), gated by the min-requests floor."""
    if overall.request_count < policy.min_requests:
        return []  # too little traffic to trust — don't fire on noise

    alerts: list[Alert] = []
    if overall.error_rate is not None and overall.error_rate > policy.max_error_rate:
        alerts.append(
            Alert(
                kind="error_rate_high",
                scope="overall",
                observed=overall.error_rate,
                threshold=policy.max_error_rate,
                message=(
                    f"error rate {overall.error_rate:.1%} exceeds "
                    f"{policy.max_error_rate:.1%} over {overall.request_count} requests"
                ),
            )
        )

    cost_per_request = _cost_per_request(overall)
    threshold = float(policy.max_cost_per_request_usd)
    if cost_per_request is not None and cost_per_request > threshold:
        alerts.append(
            Alert(
                kind="cost_per_request_high",
                scope="overall",
                observed=cost_per_request,
                threshold=threshold,
                message=(f"cost/request ${cost_per_request:.6f} exceeds ${threshold:.6f}"),
            )
        )
    return alerts


def _quality_alerts(metrics: PromptMetrics, policy: AlertPolicy) -> list[Alert]:
    """Per-version quality: below the floor, and regression vs the previous version.

    ``by_version`` is oldest-first, so 'the previous version' is simply the last one we saw with a
    quality number — the natural baseline for an immutable, ordered version history. Unevaluated
    versions (``quality is None``) are skipped *without* resetting the baseline, so "previous
    version" really means "previous **evaluated** version" — a regression is still caught across a
    version that was never evaluated, rather than being masked by the gap.
    """
    alerts: list[Alert] = []
    previous_quality: float | None = None
    for version in metrics.by_version:
        quality = version.quality
        if quality is None:
            continue  # not evaluated — nothing to judge (stays distinct from "scored 0")

        if quality < policy.min_quality:
            alerts.append(
                Alert(
                    kind="quality_below_threshold",
                    scope=f"version:{version.version_number}",
                    observed=quality,
                    threshold=policy.min_quality,
                    message=(
                        f"version {version.version_number} quality {quality:.2f} "
                        f"below minimum {policy.min_quality:.2f}"
                    ),
                )
            )

        if previous_quality is not None and (previous_quality - quality) > policy.max_quality_drop:
            alerts.append(
                Alert(
                    kind="quality_regression",
                    scope=f"version:{version.version_number}",
                    observed=quality,
                    threshold=previous_quality - policy.max_quality_drop,
                    message=(
                        f"version {version.version_number} quality {quality:.2f} dropped more than "
                        f"{policy.max_quality_drop:.2f} from the previous version "
                        f"({previous_quality:.2f})"
                    ),
                )
            )
        previous_quality = quality
    return alerts


def _cost_per_request(block: MetricsBlock) -> float | None:
    """Average cost per request, or ``None`` when there's no cost or no requests to divide by."""
    if block.total_cost_usd is None or block.request_count == 0:
        return None
    return float(block.total_cost_usd) / block.request_count
