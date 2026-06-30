"""Audit log router — admin-only surface for the promotion audit trail.

Exposes GET /audit-log which maps the promotion_audits table (append-only, written by
PromotionGate) to the generic AuditEvent shape the Activity page expects. Each row
becomes one event: actor, action (promoted|blocked), the prompt+label+version as target,
and timestamp.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from promptforge_api.authz import require_admin
from promptforge_api.db.engine import get_session
from promptforge_api.repositories.promotion import PromotionAuditRepository
from promptforge_api.schemas import AuditEventResponse, AuditLogPage

router = APIRouter(tags=["audit"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/audit-log", dependencies=[Depends(require_admin)])
def list_audit_log(
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
) -> AuditLogPage:
    """Return a page of audited actions, newest first. Admin-only."""
    repo = PromotionAuditRepository(session)
    rows = repo.list_all(limit=limit, offset=offset)
    total = repo.count_all()
    events = [
        AuditEventResponse(
            id=str(audit.id),
            actor=audit.actor,
            action=audit.decision,
            target=f"{name}:{audit.label} → v{audit.to_version_number}",
            timestamp=audit.created_at.isoformat(),
        )
        for audit, name in rows
    ]
    return AuditLogPage(events=events, total=total)
