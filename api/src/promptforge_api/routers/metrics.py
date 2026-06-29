"""HTTP layer for observability metrics — one read-only endpoint per prompt.

``GET /prompts/{name}/metrics?window=7d`` returns the prompt's latency percentiles, error rate,
spend, and per-version quality over a recent window — the Phase 7 data layer the UI dashboards
(Sprint 16) will later render. This is *data only*: numbers, not charts and not time-bucketed
series. Handlers are ``def`` (threadpool) so the sync DB session never blocks the loop (ADR 0003).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from promptforge_api.db.engine import get_session
from promptforge_api.repositories.metrics import (
    MetricsRepository,
    SourceCost,
    VersionMetrics,
)
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.routers._mappers import block_dto, bucket_dto, money
from promptforge_api.schemas import (
    PromptMetricsResponse,
    PromptTimeseriesResponse,
    SourceCostDTO,
    VersionMetricsDTO,
)
from promptforge_api.services.metrics import MetricsService, PromptMetrics, PromptTimeseries

router = APIRouter(tags=["metrics"])

SessionDep = Annotated[Session, Depends(get_session)]

# The query windows the endpoint accepts; FastAPI validates the param against this set (422 on a
# bad value). Mirrors the keys of ``services.metrics.WINDOWS`` — keep the two in sync.
MetricsWindow = Literal["24h", "7d", "30d"]

# The bucket sizes the time-series endpoint accepts. Optional on the wire (defaults from the
# window); mirrors ``services.metrics.INTERVALS`` — keep the two in sync.
MetricsInterval = Literal["hour", "day"]


def _version_dto(version: VersionMetrics) -> VersionMetricsDTO:
    return VersionMetricsDTO(
        version_number=version.version_number,
        prompt_version_id=version.prompt_version_id,
        quality=version.quality,
        metrics=block_dto(version.metrics),
    )


def _source_dto(source: SourceCost) -> SourceCostDTO:
    return SourceCostDTO(source=source.source, cost_usd=money(source.cost_usd))


def _to_response(result: PromptMetrics) -> PromptMetricsResponse:
    return PromptMetricsResponse(
        name=result.name,
        prompt_id=result.prompt_id,
        window=result.window,
        since=result.since,
        overall=block_dto(result.overall),
        by_version=[_version_dto(v) for v in result.by_version],
        by_source=[_source_dto(s) for s in result.by_source],
    )


def _to_timeseries_response(result: PromptTimeseries) -> PromptTimeseriesResponse:
    return PromptTimeseriesResponse(
        name=result.name,
        prompt_id=result.prompt_id,
        window=result.window,
        interval=result.interval,
        since=result.since,
        version=result.version,
        buckets=[bucket_dto(b) for b in result.buckets],
    )


@router.get("/prompts/{name}/metrics", response_model=PromptMetricsResponse)
def get_prompt_metrics(
    name: str, session: SessionDep, window: MetricsWindow = "7d"
) -> PromptMetricsResponse:
    """Return latency/error/cost/quality for *name* over the given window (default 7 days).

    404 if the prompt doesn't exist (raised by the service, mapped by the registered handlers).
    """
    service = MetricsService(PromptRepository(session), MetricsRepository(session))
    return _to_response(service.prompt_metrics(name=name, window=window))


@router.get("/prompts/{name}/metrics/timeseries", response_model=PromptTimeseriesResponse)
def get_prompt_metrics_timeseries(
    name: str,
    session: SessionDep,
    window: MetricsWindow = "7d",
    interval: MetricsInterval | None = None,
    version: int | None = None,
) -> PromptTimeseriesResponse:
    """Return *name*'s metrics bucketed over time — the read surface behind the trend charts.

    Buckets are gap-filled (empty time ranges come back with ``request_count`` 0, not missing), so a
    chart never draws a misleading line across a hole. ``interval`` defaults from the window
    (hourly for 24h, daily otherwise). ``version`` scopes the series to one version (the dashboard's
    per-version sparklines); omit it for the whole prompt. 404 if the prompt or version is unknown.
    """
    service = MetricsService(PromptRepository(session), MetricsRepository(session))
    return _to_timeseries_response(
        service.prompt_timeseries(name=name, window=window, interval=interval, version=version)
    )
