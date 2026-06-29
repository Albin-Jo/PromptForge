"""Security scanning — the safety axis of the promotion gate (Sprint 12 / Phase 10).

Where the eval engine asks *is this prompt good enough?*, scanning asks *is this prompt
safe enough?* — does its text carry a prompt-injection attempt, leaked secrets, PII, or a
known jailbreak pattern? The two are orthogonal gates on the same promotion.

The public seam is small and mirrors the eval engine on purpose:

- :class:`Finding` — one thing a scanner flagged (category, severity, evidence, why).
- :class:`Severity` — the ordered low/medium/high scale a scan rolls up to a risk level.
- :class:`Scanner` — the pluggable interface every detector implements (async, like
  :class:`~promptforge_api.evals.scorer.Scorer`).

Honest framing (defense-in-depth): these scanners are **signals that raise the cost of a
mistake**, not a guarantee. They will miss novel attacks and occasionally flag benign text;
the default posture is *warn*, with *gate-on-high-severity* as an opt-in (ADR, task 13).
"""

from promptforge_api.scanning.finding import Category, Finding, Severity
from promptforge_api.scanning.scanner import Scanner

__all__ = ["Category", "Finding", "Scanner", "Severity"]
