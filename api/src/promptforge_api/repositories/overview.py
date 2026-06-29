"""Read-model for the fleet overview — the cross-prompt rollup behind the landing page (ADR 0022).

Where :mod:`metrics` answers "how is *this* prompt doing?", this answers "how is the *whole fleet*
doing, and which prompts need attention?". It deliberately spans four subsystems — the registry
(prompts + their latest version), traces (per-prompt traffic), evals (latest quality), and scans
(latest risk) — but does so in a handful of **batched** queries (one per subsystem), never a query
per prompt: the same N+1 discipline the per-prompt metrics read-model keeps (ADR 0014).

The service stitches these into per-prompt rollups and applies the "needs attention" rules; these
methods stay pure data-access (frozen, Pydantic-free result rows).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.db.trace_models import Trace


@dataclass(frozen=True)
class PromptRow:
    """Registry facts for one prompt: identity, its latest version, and how many versions exist."""

    prompt_id: uuid.UUID
    name: str
    updated_at: datetime
    latest_version_number: int | None
    latest_version_id: uuid.UUID | None
    version_count: int


@dataclass(frozen=True)
class TrafficRow:
    """One prompt's trace aggregates over the window (mirrors a MetricsBlock's numbers)."""

    request_count: int
    error_count: int
    p95_ms: float | None
    cost_usd: Decimal | None


class OverviewRepository:
    """Batched cross-prompt queries: registry rows, per-prompt traffic, and latest scan risk."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def prompt_rows(self) -> list[PromptRow]:
        """Every prompt with its latest-version (number + id) and total version count.

        Two small queries merged in Python: a GROUP BY for counts + the max version number, and a
        ``DISTINCT ON`` for the latest version's id. Prompts with no versions yet still appear (the
        overview should list a freshly-created prompt), with ``None`` latest-version fields.
        """
        # Counts + latest version *number* per prompt (LEFT JOIN so version-less prompts survive).
        agg_rows = self._session.execute(
            select(
                Prompt.id,
                Prompt.name,
                Prompt.updated_at,
                func.max(PromptVersion.version_number).label("latest_version"),
                func.count(PromptVersion.id).label("version_count"),
            )
            .join(PromptVersion, PromptVersion.prompt_id == Prompt.id, isouter=True)
            .group_by(Prompt.id, Prompt.name, Prompt.updated_at)
            .order_by(Prompt.name)
        ).all()

        # The latest version's *id* per prompt (DISTINCT ON keeps the highest version_number row).
        # Comprehension, not dict(rows): a SQLAlchemy Row isn't a plain tuple, so dict() loses the
        # key/value types for mypy — hence the C416 suppression (also below).
        latest_versions = self._session.execute(
            select(PromptVersion.prompt_id, PromptVersion.id)
            .distinct(PromptVersion.prompt_id)
            .order_by(PromptVersion.prompt_id, PromptVersion.version_number.desc())
        ).all()
        latest_id_by_prompt = {prompt_id: version_id for prompt_id, version_id in latest_versions}  # noqa: C416

        return [
            PromptRow(
                prompt_id=prompt_id,
                name=name,
                updated_at=updated_at,
                latest_version_number=latest_version,
                latest_version_id=latest_id_by_prompt.get(prompt_id),
                version_count=version_count,
            )
            for prompt_id, name, updated_at, latest_version, version_count in agg_rows
        ]

    def traffic_by_prompt(self, since: datetime) -> dict[uuid.UUID, TrafficRow]:
        """Per-prompt trace aggregates over the window, keyed by prompt id.

        Only version/prompt-linked traces with a non-null ``prompt_id`` (a fleet view is per
        *prompt*); a prompt with no traffic in the window is simply absent from the map, and the
        service treats that as a real zero.
        """
        rows = self._session.execute(
            select(
                Trace.prompt_id,
                func.count().label("n"),
                func.count().filter(Trace.status == "error").label("errors"),
                func.percentile_cont(0.95).within_group(Trace.latency_ms.asc()).label("p95"),
                func.sum(Trace.cost_usd).label("cost"),
            )
            .where(Trace.prompt_id.is_not(None), Trace.created_at >= since)
            .group_by(Trace.prompt_id)
        ).all()
        return {
            prompt_id: TrafficRow(request_count=n, error_count=errors, p95_ms=p95, cost_usd=cost)
            for prompt_id, n, errors, p95, cost in rows
        }

    def latest_scan_risk_by_version(
        self, version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        """The latest *completed* scan's ``risk_level`` per version (``DISTINCT ON``).

        Versions never scanned (or whose latest scan isn't completed) are absent — the service reads
        that as "unscanned". Mirrors :meth:`MetricsRepository.latest_eval_summary_by_version`.
        """
        if not version_ids:
            return {}
        rows = self._session.execute(
            select(SecurityScan.prompt_version_id, SecurityScan.risk_level)
            .where(
                SecurityScan.prompt_version_id.in_(version_ids),
                SecurityScan.status == "completed",
            )
            .distinct(SecurityScan.prompt_version_id)
            .order_by(SecurityScan.prompt_version_id, SecurityScan.created_at.desc())
        ).all()
        return {version_id: risk for version_id, risk in rows}  # noqa: C416  (Row, not tuple)
