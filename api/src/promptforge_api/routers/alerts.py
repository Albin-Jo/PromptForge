"""HTTP layer for drift/regression alerts — surface the breaches over a window.

``GET /prompts/{name}/alerts?window=7d`` evaluates the config thresholds against the prompt's
metrics (the task-3 read-model) and returns whatever is currently firing. Each fired alert is also
written as a structured ``drift_alert`` warning, so a breach is visible in the logs even when no one
is polling the endpoint — the headless platform's stand-in for delivery (email/webhook is later).
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from promptforge_api.config import get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.repositories.metrics import MetricsRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.routers.metrics import MetricsWindow
from promptforge_api.schemas import AlertDTO, AlertsResponse
from promptforge_api.services.alerts import Alert, AlertPolicy, evaluate_alerts
from promptforge_api.services.metrics import MetricsService

router = APIRouter(tags=["metrics"])
_logger = structlog.get_logger(__name__)

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/prompts/{name}/alerts", response_model=AlertsResponse)
def get_prompt_alerts(
    name: str, session: SessionDep, window: MetricsWindow = "7d"
) -> AlertsResponse:
    """Return the drift/regression alerts firing for *name* over the window (empty if healthy).

    404 if the prompt doesn't exist (raised by the metrics service, mapped by the handlers).
    """
    metrics = MetricsService(PromptRepository(session), MetricsRepository(session)).prompt_metrics(
        name=name, window=window
    )

    policy = AlertPolicy.from_settings(get_settings())
    alerts = evaluate_alerts(metrics, policy)

    for alert in alerts:
        _logger.warning(
            "drift_alert",
            prompt=name,
            window=window,
            kind=alert.kind,
            scope=alert.scope,
            observed=alert.observed,
            threshold=alert.threshold,
        )

    return AlertsResponse(name=name, window=window, alerts=[_dto(a) for a in alerts])


def _dto(alert: Alert) -> AlertDTO:
    return AlertDTO(
        kind=alert.kind,
        scope=alert.scope,
        observed=alert.observed,
        threshold=alert.threshold,
        message=alert.message,
    )
