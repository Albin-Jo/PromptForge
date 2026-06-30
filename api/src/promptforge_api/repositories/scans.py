"""Data access for security scans — create a scan and look up a version's scan history.

The persistence half of the scanning API surface, mirroring :class:`EvalRepository`: no business
rules here (the service owns *what* an operation means), only *how* it talks to the database. The
gate (task 13) reads ``latest_completed_for_version`` the same way it reads the latest eval.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.db.scan_models import SecurityScan


class ScanRepository:
    """Persistence for security scans."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def flush(self) -> None:
        """Emit pending INSERTs now so DB-side defaults/ids are populated."""
        self._session.flush()

    def add(self, scan: SecurityScan) -> None:
        """Stage a new scan for insert."""
        self._session.add(scan)

    def get(self, scan_id: uuid.UUID) -> SecurityScan | None:
        """Fetch a single scan by id."""
        return self._session.get(SecurityScan, scan_id)

    def latest_for_version(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        """The most recent scan for a version, *any* status (to detect an in-flight scan)."""
        stmt = (
            select(SecurityScan)
            .where(SecurityScan.prompt_version_id == prompt_version_id)
            .order_by(SecurityScan.created_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).one_or_none()

    def list_for_version(
        self, prompt_version_id: uuid.UUID, *, limit: int
    ) -> list[SecurityScan]:
        """A version's scans, newest first, capped at ``limit`` (the scan-history list).

        Findings live on the row as a JSONB blob, so the history loads with no extra join —
        the same shape the latest-status read uses, just unbounded by ``.limit(1)``.
        """
        stmt = (
            select(SecurityScan)
            .where(SecurityScan.prompt_version_id == prompt_version_id)
            .order_by(SecurityScan.created_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def latest_completed_for_version(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        """The most recent *completed* scan for a version (the gate's source of risk_level)."""
        stmt = (
            select(SecurityScan)
            .where(
                SecurityScan.prompt_version_id == prompt_version_id,
                SecurityScan.status == "completed",
            )
            .order_by(SecurityScan.created_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).one_or_none()
