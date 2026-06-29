"""What a scanner produces — a finding, its severity, and the category it belongs to.

These are the domain types every scanner speaks, the safety-side counterpart to
:class:`~promptforge_api.evals.scorer.Score`. Plain frozen dataclasses + enums: produced
inside the trusted core, so no Pydantic here (CLAUDE.md: Pydantic at the boundary,
dataclasses inside).

A :class:`Finding` is deliberately scanner-agnostic — a regex secret match, an entropy
hit, an NER PII span, and an LLM-judge injection verdict all serialise to the same shape —
so the runner can collect findings from every scanner without branching on which produced
them, and the :class:`~promptforge_api.db.scan_models.SecurityScan` row can store them as one
JSONB list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """How bad a finding is, on an ordered low → medium → high scale.

    A :class:`~enum.StrEnum`, so it *is* its string value — it serialises straight into JSONB and
    reads as ``"high"`` on the wire, not an opaque integer. Three levels on purpose — the
    promotion gate keys on ``HIGH`` and more rungs would be precision we can't honestly calibrate
    for v0.1. A scan rolls its findings up to the *maximum* severity via :meth:`max_of` (see
    ``SecurityScan.risk_level``).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        """Numeric weight for ordering/comparison (higher = more severe)."""
        return _SEVERITY_RANK[self]

    @classmethod
    def max_of(cls, severities: list[Severity]) -> Severity | None:
        """The most severe of *severities*, or ``None`` for an empty list (a clean scan)."""
        return max(severities, key=lambda s: s.rank) if severities else None


# Defined after the class so the members exist; keeps Severity.rank a cheap lookup.
_SEVERITY_RANK: dict[Severity, int] = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}


class Category(StrEnum):
    """The class of safety problem a finding belongs to — one per scanner family.

    Stored on each finding so the UI/API can group ("3 secret findings, 1 injection") and the
    gate can, if we ever want, treat categories differently. A :class:`~enum.StrEnum` for the
    same JSONB-readability reason as :class:`Severity`.
    """

    INJECTION = "injection"
    PII = "pii"
    SECRET = "secret"
    JAILBREAK = "jailbreak"


@dataclass(frozen=True)
class Finding:
    """One thing a scanner flagged in the scanned text.

    - ``category`` — which family of problem (:class:`Category`).
    - ``severity`` — how bad (:class:`Severity`); drives the scan's ``risk_level`` rollup and
      the gate decision.
    - ``detector`` — the specific rule/heuristic that fired (e.g. ``"aws_access_key_id"``,
      ``"shannon_entropy"``, ``"llm_judge"``). Stable id so a noisy rule can be found and tuned.
    - ``message`` — human-readable *what* ("Possible AWS access key id"). What a reviewer reads.
    - ``evidence`` — the offending snippet, **already redacted by the scanner** for secrets/PII
      (e.g. ``"AKIA…last4"``). We never store a live secret back into our own database.
    - ``span`` — optional ``(start, end)`` char offsets into the scanned text, so a UI can
      highlight the match. ``None`` when a detector (e.g. the LLM judge) reasons over the whole
      text and can't point at one span.
    - ``metadata`` — detector-specific extras (entropy value, judge confidence, regex name).
      Free-form; never load-bearing for control flow.
    """

    category: Category
    severity: Severity
    detector: str
    message: str
    evidence: str = ""
    span: tuple[int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the JSONB shape stored on ``SecurityScan.findings``.

        ``span`` becomes a 2-element list (JSON has no tuple); enums become their string
        values. The inverse of :meth:`from_dict`.
        """
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "detector": self.detector,
            "message": self.message,
            "evidence": self.evidence,
            "span": list(self.span) if self.span is not None else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        """Rebuild a Finding from its stored JSONB form (the inverse of :meth:`to_dict`)."""
        span = data.get("span")
        return cls(
            category=Category(data["category"]),
            severity=Severity(data["severity"]),
            detector=data["detector"],
            message=data["message"],
            evidence=data.get("evidence", ""),
            span=(span[0], span[1]) if span is not None else None,
            metadata=data.get("metadata", {}),
        )
