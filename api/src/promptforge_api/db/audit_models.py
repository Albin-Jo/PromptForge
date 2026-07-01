"""ORM model for the audit trail — the platform's "who did what, when" record.

Grew out of the promotion trail (Sprint 11): originally one row per attempt to move the gated
label, it now records every audited action — version creates, non-gated label moves, golden-set
attach/detach, and user creation — alongside the promote/block decisions (ADR 0028).

Append-only by intent: an audited action is a historical fact, never edited. Every row carries the
**actor** (the authenticated user's email, or ``system``), the **action** verb (an open, code-owned
vocabulary), the human-readable **target**, and an optional ``detail`` JSONB. The promotion-specific
columns (``label``, the from/to versions, ``reason``) are retained but **nullable** — a promotion
fills them and keeps its rich record; a ``user_created`` event leaves them NULL.

Persistence entity, not an API DTO (CLAUDE.md). The correlation id is not a column here — it rides
the audit-write log line via structlog contextvars (ADR 0028).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base


class AuditEvent(Base):
    """One audited action (e.g. promoted | version_created | user_created)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The actor who triggered it: the authenticated user's email, an "api-key:<prefix>" for the
    # legacy promotion path, or "system" when auth is off.
    actor: Mapped[str] = mapped_column(String(255), default="system")
    # The action verb. An open, code-owned vocabulary (no DB CHECK any more) — promoted | blocked |
    # version_created | label_set | golden_set_attached | golden_set_detached | user_created.
    action: Mapped[str] = mapped_column(String(64))
    # The human-readable subject the Activity page shows — e.g. "support-bot v4" or
    # "user:bob@x.com (editor)". Self-contained so the reader needs no join.
    target: Mapped[str | None] = mapped_column(Text, default=None)

    # --- promotion-specific columns: filled by the gate, NULL for other events. ---
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), default=None, index=True
    )
    # The label whose move was decided (e.g. "production"). NULL for non-label events.
    label: Mapped[str | None] = mapped_column(String(255), default=None)
    # The candidate promoted. SET NULL keeps the audit after a version is deleted;
    # to_version_number preserves the human-readable identity regardless.
    to_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    to_version_number: Mapped[int | None] = mapped_column(default=None)
    # What the label pointed at before. NULL for a first-ever promotion or a non-promotion event.
    from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    from_version_number: Mapped[int | None] = mapped_column(default=None)
    # Human-readable summary of why (the promotion gate's verdict). NULL for events with no verdict.
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    # Machine-readable evidence (e.g. the gate's per-metric deltas + deciding eval_run_id).
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
