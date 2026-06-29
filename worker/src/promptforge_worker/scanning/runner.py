"""The scan runner: load a version's text, run every scanner over it, persist the findings.

The scanning counterpart to :class:`~promptforge_worker.evals.runner.EvalRunner` — what the
``run_scan`` Celery task drives. Given a :class:`SecurityScan` (which names a prompt *version*), it:

1. **loads** the version and takes its raw ``content`` as the text to scan (Sprint 12 decision:
   the author's template text, ``{{placeholders}}`` left literal — not the variable-filled render).
   **Coverage gap (backlog):** this is *only* the version's own ``content``. The block contents a
   composed prompt pulls in are NOT scanned — block-version saves have no scan hook yet, and we
   don't resolve composition here — so a secret/injection hidden inside an included block is missed
   until composed-text (or block-on-save) scanning lands. The ADR records this.
2. **scans** — runs every registered scanner over the text through the one ``Scanner`` protocol;
3. **rolls up** — records the findings, the effective scanner set, and the worst severity as the
   scan's ``risk_level`` (the column the promotion gate reads).

Like the eval runner it owns no transaction or status: the task passes a live session and manages
the scan lifecycle (pending → completed | failed), so the whole scan commits or rolls back as one.

The scanned text is **untrusted** (a prompt author can write anything), so the scanners' regexes
are kept linear — no nested/overlapping quantifiers — to avoid catastrophic backtracking. A
runaway pattern would hang a worker thread (off the request path), not the API; a per-scan
wall-clock budget is a deliberate non-goal for v0.1 (backlog).

**Error policy** mirrors the eval runner: a *retryable* gateway failure (the injection scanner's
LLM pass) is re-raised as :class:`TransientScanError` so the task retries the whole scan; anything
else (a bad version reference, a scanner bug) is permanent and fails the scan. A scanner returning
an empty list is the normal "clean" outcome, never an error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.orm import Session

from promptforge_api.db.models import PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.gateway import LLMGateway
from promptforge_api.gateway.errors import RETRYABLE_ERRORS, GatewayError
from promptforge_api.scanning import Finding, Scanner, Severity
from promptforge_worker.errors import TransientScanError
from promptforge_worker.scanning.registry import build_scanners

_logger = structlog.get_logger(__name__)


class ScanConfigError(ValueError):
    """The scan is unrunnable as configured — no version id, or the version is gone."""


class ScanNotFoundError(LookupError):
    """The scan id handed to the task doesn't exist — a permanent failure, not worth retrying."""


class ScanRunner:
    """Runs every scanner over a version's text for a :class:`SecurityScan`, persisting findings."""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        scanner_builder: Callable[[LLMGateway], list[Scanner]] = build_scanners,
    ) -> None:
        # The builder is injectable so tests can supply fake scanners (and so the spine is
        # testable end-to-end before any real scanner is registered); production uses the registry.
        self._gateway = gateway
        self._build_scanners = scanner_builder

    async def run(self, session: Session, scan: SecurityScan) -> dict[str, Any]:
        """Scan *scan*'s version text, persist findings + risk_level, and return a small summary.

        The caller owns the transaction and the status lifecycle; this method only reads the
        version, writes the results onto *scan*, and returns a summary for the task to log.
        """
        text = self._load_text(session, scan)
        scanners: list[Scanner] = self._build_scanners(self._gateway)

        findings: list[Finding] = []
        for scanner in scanners:
            findings.extend(await self._run_one(scanner, text))

        risk = Severity.max_of([f.severity for f in findings])
        scan.scanners = [s.name for s in scanners]
        scan.findings = [f.to_dict() for f in findings]
        scan.risk_level = risk.value if risk is not None else "none"

        summary = {
            "risk_level": scan.risk_level,
            "findings": len(findings),
            "scanners": scan.scanners,
        }
        _logger.info("scan_completed", security_scan_id=str(scan.id), **summary)
        return summary

    # --- internals ---------------------------------------------------------------------------

    @staticmethod
    def _load_text(session: Session, scan: SecurityScan) -> str:
        """Resolve the version's text to scan, or fail with a permanent config error."""
        if scan.prompt_version_id is None:
            raise ScanConfigError("security scan has no prompt_version_id to scan")
        version = session.get(PromptVersion, scan.prompt_version_id)
        if version is None:
            raise ScanConfigError(f"prompt version {scan.prompt_version_id} not found")
        return version.content

    @staticmethod
    async def _run_one(scanner: Scanner, text: str) -> list[Finding]:
        """Run one scanner, classifying a gateway failure as retry-the-scan vs fail-the-scan."""
        try:
            return await scanner.scan(text=text)
        except GatewayError as exc:
            # The gateway already exhausted its internal retries; a retryable error gets the whole
            # scan another attempt under the task's backoff, a permanent one fails the scan.
            if isinstance(exc, RETRYABLE_ERRORS):
                raise TransientScanError(f"retryable gateway failure during scan: {exc}") from exc
            raise
