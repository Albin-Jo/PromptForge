"""HTTP layer for the fleet overview — one read-only endpoint behind the landing page (ADR 0022).

``GET /overview?window=7d`` returns fleet totals, a gap-filled trend, and a per-prompt rollup with
"needs attention" flags. Like the metrics router this is *data only* (numbers + flag keys, no
prose), and ``def`` (threadpool) so the sync DB session never blocks the loop (ADR 0003).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from promptforge_api.db.engine import get_session
from promptforge_api.repositories.metrics import MetricsRepository
from promptforge_api.repositories.overview import OverviewRepository
from promptforge_api.routers._mappers import block_dto, bucket_dto, money
from promptforge_api.schemas import (
    OverviewResponse,
    PromptRollupDTO,
)
from promptforge_api.services.overview import FleetOverview, OverviewService, PromptRollup

router = APIRouter(tags=["overview"])

SessionDep = Annotated[Session, Depends(get_session)]

# Same closed sets as the metrics router (the overview shares the window/interval contract).
MetricsWindow = Literal["24h", "7d", "30d"]
MetricsInterval = Literal["hour", "day"]


def _rollup_dto(rollup: PromptRollup) -> PromptRollupDTO:
    return PromptRollupDTO(
        name=rollup.name,
        latest_version=rollup.latest_version,
        request_count=rollup.request_count,
        error_rate=rollup.error_rate,
        p95_ms=rollup.p95_ms,
        cost_usd=money(rollup.cost_usd),
        quality=rollup.quality,
        attention=rollup.attention,
    )


def _to_response(result: FleetOverview) -> OverviewResponse:
    return OverviewResponse(
        window=result.window,
        interval=result.interval,
        since=result.since,
        totals=block_dto(result.totals),
        trend=[bucket_dto(b) for b in result.trend],
        prompts=[_rollup_dto(p) for p in result.prompts],
    )


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    session: SessionDep,
    window: MetricsWindow = "7d",
    interval: MetricsInterval | None = None,
) -> OverviewResponse:
    """Return the fleet overview: totals, trend, and the per-prompt rollup with attention flags."""
    service = OverviewService(MetricsRepository(session), OverviewRepository(session))
    return _to_response(service.fleet_overview(window=window, interval=interval))
