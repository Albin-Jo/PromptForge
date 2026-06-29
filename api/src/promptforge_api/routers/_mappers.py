"""Shared domain→DTO mappers for the metrics and overview routers.

Both routers render the same building blocks — a money Decimal, a :class:`MetricsBlock`, and a
:class:`MetricsBucket` — so the mapping lives here once rather than being copied per router. These
stay thin (no logic, just shape translation); router-specific composites (per-version, per-source,
the full responses) live next to their endpoints.
"""

from __future__ import annotations

from decimal import Decimal

from promptforge_api.repositories.metrics import MetricsBlock, MetricsBucket
from promptforge_api.schemas import LatencyPercentilesDTO, MetricsBlockDTO, MetricsBucketDTO


def money(value: Decimal | None) -> str | None:
    """Render a money Decimal as an exact string for the wire (None stays None)."""
    return str(value) if value is not None else None


def block_dto(block: MetricsBlock) -> MetricsBlockDTO:
    return MetricsBlockDTO(
        request_count=block.request_count,
        error_count=block.error_count,
        error_rate=block.error_rate,
        latency=LatencyPercentilesDTO(
            p50_ms=block.latency.p50_ms,
            p95_ms=block.latency.p95_ms,
            p99_ms=block.latency.p99_ms,
        ),
        total_cost_usd=money(block.total_cost_usd),
    )


def bucket_dto(bucket: MetricsBucket) -> MetricsBucketDTO:
    return MetricsBucketDTO(
        bucket_start=bucket.bucket_start,
        request_count=bucket.request_count,
        error_rate=bucket.error_rate,
        p95_ms=bucket.p95_ms,
        cost_usd=money(bucket.cost_usd),
        quality=bucket.quality,
    )
