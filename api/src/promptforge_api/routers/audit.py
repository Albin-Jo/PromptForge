"""Audit log router — admin-only surface for the platform's audit trail.

Exposes GET /audit-log, which maps the append-only ``audit_events`` table (ADR 0028) to the generic
AuditEvent shape the Activity page expects. Each row becomes one event: actor, action, the
human-readable target, and timestamp. An optional ``action`` filter narrows to one kind of event.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from promptforge_api.authz import require_admin
from promptforge_api.db.engine import get_session
from promptforge_api.repositories.audit import AuditRepository
from promptforge_api.schemas import AuditEventResponse, AuditLogPage

router = APIRouter(tags=["audit"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/audit-log", dependencies=[Depends(require_admin)])
def list_audit_log(
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
) -> AuditLogPage:
    """Return a page of audited actions, newest first. Admin-only; optionally filtered by action."""
    repo = AuditRepository(session)
    rows = repo.list_all(limit=limit, offset=offset, action=action)
    total = repo.count_all(action=action)
    events = [
        AuditEventResponse(
            id=str(event.id),
            actor=event.actor,
            action=event.action,
            target=event.target or "—",
            timestamp=event.created_at.isoformat(),
        )
        for event in rows
    ]
    return AuditLogPage(events=events, total=total)
