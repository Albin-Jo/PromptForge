"""ORM model for the promotion audit log — the system of record for *deployments*.

Every attempt to move the gated label (``production``) writes one row here, whether it
**promoted** or was **blocked** by the eval gate (Sprint 11 / Phase 8). This is the
"who promoted what, when, and why was it (not) allowed" trail the build plan calls for.

Append-only by intent: a promotion decision is a historical fact, never edited. The row
captures the *decision*, the *actor*, the from/to versions (both id and number, so the
record survives a version being deleted — the ids SET NULL but the numbers remain), and
a free-form ``detail`` JSONB carrying the gate's per-metric deltas + the deciding eval
run, so a blocked promotion is fully explainable after the fact.

Persistence entity, not an API DTO (CLAUDE.md). "who" is the API key / ``system`` for
v0.1 — real user identity arrives with auth in Sprint 13.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base


class PromotionAudit(Base):
    """One promotion decision (promoted | blocked) on a prompt's gated label."""

    __tablename__ = "promotion_audits"
    __table_args__ = (
        # A closed set of outcomes; the CHECK keeps a typo'd decision out of the trail.
        CheckConstraint("decision IN ('promoted', 'blocked')", name="decision_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), index=True
    )
    # The label whose move was decided (e.g. "production"). Stored, not assumed, so the
    # trail stays correct if the gated label is ever reconfigured.
    label: Mapped[str] = mapped_column(String(255))
    # The candidate being promoted. SET NULL keeps the audit after a version is deleted;
    # to_version_number preserves the human-readable identity regardless.
    to_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    to_version_number: Mapped[int] = mapped_column()
    # What the label pointed at before this decision. NULL for the first-ever promotion
    # (no incumbent) or after the prior version is deleted.
    from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    from_version_number: Mapped[int | None] = mapped_column(default=None)
    decision: Mapped[str] = mapped_column(String(16))
    # Human-readable summary of why (e.g. "scorer llm_judge regressed 0.20 below production").
    reason: Mapped[str] = mapped_column(Text)
    # Who triggered it: "api-key:<prefix>" when a key was presented, else "system".
    actor: Mapped[str] = mapped_column(String(255), default="system")
    # Machine-readable evidence: the gate's per-metric deltas, the candidate summary, and
    # the deciding eval_run_id — everything needed to explain the decision after the fact.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
