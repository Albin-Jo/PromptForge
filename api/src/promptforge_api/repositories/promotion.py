"""Data access for the promotion audit trail (Sprint 11 / Phase 8).

Append-only: a promotion decision is a historical fact. The repository only stages
inserts and reads history back — there is deliberately no update path, mirroring how
the registry repository never offers a way to mutate an immutable version.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.db.promotion_models import PromotionAudit


class PromotionAuditRepository:
    """Persistence for :class:`PromotionAudit` rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, audit: PromotionAudit) -> None:
        """Stage a new audit row for insert."""
        self._session.add(audit)

    def flush(self) -> None:
        """Emit the pending INSERT now so the row's id/created_at are populated."""
        self._session.flush()

    def list_for_prompt(self, prompt_id: uuid.UUID) -> list[PromotionAudit]:
        """Return a prompt's promotion history, newest first."""
        stmt = (
            select(PromotionAudit)
            .where(PromotionAudit.prompt_id == prompt_id)
            .order_by(PromotionAudit.created_at.desc())
        )
        return list(self._session.scalars(stmt))
