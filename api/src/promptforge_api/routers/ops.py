"""HTTP layer for operational health: Celery queue depth + worker liveness (Sprint 29 T3).

There is no in-app view of the async backbone today — only single-job polling, with Flower as a
separate operator tool. ``GET /admin/queues`` surfaces per-queue backlog, the online worker count,
and how many tasks are running, so an admin can see at a glance whether the workers are keeping up.
It degrades gracefully: a broker outage returns an ``available: false`` view, never a 500.

The whole router carries ``require_admin`` — this is operational data, not public.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from promptforge_api.authz import require_admin
from promptforge_api.schemas import QueueDepthDTO, QueueHealthResponse
from promptforge_api.services.queues import (
    QueueHealth,
    QueueInspector,
    get_queue_inspector,
    read_queue_health,
)

router = APIRouter(prefix="/admin", tags=["ops"], dependencies=[Depends(require_admin)])

InspectorDep = Annotated[QueueInspector, Depends(get_queue_inspector)]


@router.get("/queues", response_model=QueueHealthResponse)
def get_queue_health(inspector: InspectorDep) -> QueueHealthResponse:
    """Return Celery queue depth + worker liveness (admin only; degrades if the broker is down)."""
    return _dto(read_queue_health(inspector))


def _dto(health: QueueHealth) -> QueueHealthResponse:
    return QueueHealthResponse(
        available=health.available,
        workers=health.workers,
        active=health.active,
        queued=health.queued,
        queues=(
            [QueueDepthDTO(name=q.name, depth=q.depth) for q in health.queues]
            if health.queues is not None
            else None
        ),
    )
