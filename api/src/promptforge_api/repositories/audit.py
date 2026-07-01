"""Data access for the audit trail (ADR 0028).

Append-only: an audited action is a historical fact. The repository stages inserts and reads the
trail back; there is deliberately no update path. Two write shapes:

- ``add``/``flush`` — used by the promotion gate, which builds a full :class:`AuditEvent` (with its
  from/to versions and per-metric ``detail``) itself.
- ``record`` — the convenience the authoring services use: actor + action + target (+ optional
  ``detail``), leaving the promotion-only columns NULL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptforge_api.db.audit_models import AuditEvent


class AuditRepository:
    """Persistence for :class:`AuditEvent` rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        """Stage a fully-built audit row for insert (the promotion gate's path)."""
        self._session.add(event)

    def flush(self) -> None:
        """Emit the pending INSERT now so the row's id/created_at are populated."""
        self._session.flush()

    def record(
        self, *, actor: str, action: str, target: str, detail: dict[str, Any] | None = None
    ) -> AuditEvent:
        """Append a generic audit event (an authoring action) and flush it."""
        event = AuditEvent(actor=actor, action=action, target=target, detail=detail)
        self._session.add(event)
        self._session.flush()
        return event

    def list_all(
        self, *, limit: int, offset: int, action: str | None = None
    ) -> list[AuditEvent]:
        """Return a page of audit events, newest first, optionally filtered by action."""
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())
        if action is not None:
            stmt = stmt.where(AuditEvent.action == action)
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))

    def count_all(self, *, action: str | None = None) -> int:
        """Total number of audit events (for pagination), optionally filtered by action."""
        stmt = select(func.count()).select_from(AuditEvent)
        if action is not None:
            stmt = stmt.where(AuditEvent.action == action)
        return self._session.scalar(stmt) or 0


def record_audit(
    audits: AuditRepository | None, *, actor: str, action: str, target: str
) -> None:
    """Append an audit event when a repository is wired; a no-op otherwise (ADR 0028).

    A single guarded entry point so the optional-audit-sink pattern (``self._audits`` may be
    ``None`` in unit tests) isn't re-implemented in every service that records events.
    """
    if audits is not None:
        audits.record(actor=actor, action=action, target=target)
