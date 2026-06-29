"""Liveness endpoint.

Liveness only: it answers "is the process up?" and deliberately does NOT check
Postgres/Redis. A dependency-aware readiness probe (``/readyz``) is a later,
conscious addition once those services exist.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness payload returned by ``/healthz``."""

    status: str


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Return 200 while the process is alive."""
    return HealthResponse(status="ok")
