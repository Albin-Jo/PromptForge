"""ORM model for security scanning — the system of record for *safety* (Sprint 12 / Phase 10).

Where ``eval_models`` record *how good* a prompt version's outputs are, this records *how safe
its text is*: the findings a set of scanners turned up, rolled up to a single risk level the
promotion gate can read.

One entity, :class:`SecurityScan`, deliberately shaped like ``EvalRun``:

- a ``pending → running → completed | failed`` lifecycle (CHECK-constrained), because a scan
  runs off the request path on Celery just like an eval;
- ``prompt_version_id`` nullable + SET NULL, so an ad-hoc scan of pasted text has no version and
  a scan's results survive its version being deleted.

**Findings live as a JSONB list, not a child table** (unlike eval's ``scores``). The gate only
ever asks "does this scan have a high-severity finding?" — answered by the rolled-up
``risk_level`` column — and the UI only ever reads a scan's findings as a whole. We never join
or aggregate across findings of different scans, so a child table would be cost without a
query to justify it. (Decision recorded in the scanning ADR.)
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base


class SecurityScan(Base):
    """One run of the scanner set over a piece of prompt text; owns its findings + risk level."""

    __tablename__ = "security_scans"
    __table_args__ = (
        # The lifecycle is a closed set — a CHECK keeps a typo'd/invented status out of the data
        # of record, exactly as on eval_runs.
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_valid",
        ),
        # risk_level is the rolled-up max severity (or 'none' for a clean completed scan). NULL
        # while the scan hasn't completed; the CHECK pins the closed set once it's set.
        CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('none', 'low', 'medium', 'high')",
            name="risk_level_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Which prompt version's rendered text was scanned. NULL for an ad-hoc scan of pasted text
    # (the DoD's "paste a prompt"); SET NULL keeps a scan's results after a version is deleted.
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None, index=True
    )
    # The scanners this scan ran, as a list of their names (e.g. ["secret", "pii", ...]). Keeps a
    # scan self-describing — it records exactly which detectors were applied — mirroring the way
    # eval_runs.scorer_config records how a run was graded.
    scanners: Mapped[list[str]] = mapped_column(JSONB)
    # Lifecycle: pending → running → completed | failed (pinned by the CHECK above). server_default
    # backs the constraint for any non-ORM insert; the Python default keeps a freshly built,
    # not-yet-flushed scan readable in memory.
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    # Rolled-up worst severity across all findings: 'none' (clean) | 'low' | 'medium' | 'high'.
    # NULL until the scan completes. This is the column the promotion gate reads — the findings
    # blob is for humans, the risk_level is for the machine.
    risk_level: Mapped[str | None] = mapped_column(String(16), default=None)
    # Every finding from every scanner, as a list of Finding.to_dict() shapes. NULL until the
    # scan completes; an empty list means "completed and clean".
    findings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
