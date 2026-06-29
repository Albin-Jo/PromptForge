"""The security gate's *decision rule* — pure policy, no I/O (Sprint 12 / Phase 10).

The safety-side counterpart to :mod:`promptforge_api.promotion`. Where that gate compares eval
summaries (a quality delta), this one is a single hard check: is the candidate's security-scan
risk level at or above the configured block threshold? Kept pure (risk level + policy in, boolean
out) so it's tested by handing it fabricated risk levels — the orchestration that loads the scan,
writes the audit, and fires the webhook lives in the ``PromotionGate`` service.

Two reasons it's *separate* from the eval ``decide`` rather than folded into it: the axes are
orthogonal (a prompt can be high-quality and unsafe, or safe and low-quality), and scanning has no
golden-set precondition — so the security check must be able to run, and block, even for a prompt
the eval gate would refuse to consider (ADR 0017).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from promptforge_api.config import Settings
from promptforge_api.scanning import Severity


@dataclass(frozen=True)
class SecurityGatePolicy:
    """How the scan result affects promotion: warn-only, or block at/above a severity."""

    mode: Literal["warn", "block"]
    block_severity: Severity

    @classmethod
    def from_settings(cls, settings: Settings) -> SecurityGatePolicy:
        return cls(
            mode=settings.scan_gate_mode,
            block_severity=Severity(settings.scan_gate_block_severity),
        )


def risk_blocks(risk_level: str | None, policy: SecurityGatePolicy) -> bool:
    """True if a completed scan's *risk_level* should block promotion under *policy*.

    Only ever true in ``block`` mode. ``None``/``"none"`` (no findings) never blocks; otherwise the
    risk level's severity rank is compared against the policy's block threshold.
    """
    if policy.mode != "block" or risk_level is None or risk_level == "none":
        return False
    return Severity(risk_level).rank >= policy.block_severity.rank
