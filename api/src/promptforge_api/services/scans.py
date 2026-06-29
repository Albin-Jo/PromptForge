"""Security-scanning use-cases exposed to the API: triggering and derived scan status.

The scanning counterpart to :class:`EvalService`. It:

- **triggers** a scan for a version — creates a ``pending`` :class:`SecurityScan` and hands its id
  to ``submit_scan`` (the Celery enqueue), the eager half of "scan on version-create";
- reports a version's derived **scan status** (unscanned / pending / running / completed / failed)
  plus its risk level, without storing that status on the immutable version row.

Two deliberate differences from eval triggering:

- **No precondition.** Eval needs a golden set; *every* version is scanned on save regardless, so
  ``trigger_on_create`` always enqueues. Safety isn't opt-in.
- **The service doesn't pick the scanners.** Which detectors run is the worker's call (it runs
  everything registered and records the effective set on the scan), so the API never hardcodes a
  scanner list or couples to the worker. The scan is created with an empty ``scanners`` the worker
  fills in when it runs.

Speaks plain arguments and ORM entities, never Pydantic (ADR 0003); the enqueue is injected so the
service never imports Celery and tests can pass a recorder.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.exceptions import PromptNotFoundError, VersionNotFoundError
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.repositories.scans import ScanRepository

_logger = structlog.get_logger(__name__)

# The enqueue side: given a freshly-created scan id, put it on the scans queue.
ScanSubmit = Callable[[uuid.UUID], None]


@dataclass(frozen=True)
class ScanStatusView:
    """A version's latest scan state, derived from its most recent scan (never stored).

    ``status`` is the scan lifecycle: ``unscanned`` (no scan), ``pending``/``running`` (in flight),
    ``completed`` (findings + risk_level ready), or ``failed`` (the scan itself errored).
    ``risk_level`` is the rolled-up worst severity once completed; ``findings`` is the full list.
    """

    prompt_version_id: uuid.UUID
    version_number: int
    status: str
    latest_scan_id: uuid.UUID | None
    risk_level: str | None
    findings: list[dict[str, Any]] | None


class ScanService:
    """Scan triggering and derived scan status."""

    def __init__(
        self,
        scan_repo: ScanRepository,
        prompt_repo: PromptRepository,
        *,
        submit_scan: ScanSubmit,
    ) -> None:
        self._scans = scan_repo
        self._prompts = prompt_repo
        self._submit_scan = submit_scan

    # ------------------------------------------------------------- triggering
    def trigger_on_create(self, prompt: Prompt, version: PromptVersion) -> SecurityScan:
        """Enqueue a security scan for a just-created version (always — no precondition).

        Called from prompt/version creation alongside the eval trigger: a version is scanned
        *eagerly* so its risk level usually exists by the time anyone tries to promote it.
        """
        return self._enqueue_scan(version.id)

    def scan_version(self, *, prompt_name: str, version_number: int) -> SecurityScan:
        """Manually (re-)trigger a scan for one version (the explicit endpoint)."""
        prompt = self._require_prompt(prompt_name)
        version = self._require_version(prompt, prompt_name, version_number)
        return self._enqueue_scan(version.id)

    # ------------------------------------------------------------------ reads
    def version_scan_status(self, *, prompt_name: str, version_number: int) -> ScanStatusView:
        """Derive a version's scan state from its most recent scan (see :class:`ScanStatusView`)."""
        prompt = self._require_prompt(prompt_name)
        version = self._require_version(prompt, prompt_name, version_number)
        latest = self._scans.latest_for_version(version.id)
        return ScanStatusView(
            prompt_version_id=version.id,
            version_number=version.version_number,
            status="unscanned" if latest is None else latest.status,
            latest_scan_id=latest.id if latest is not None else None,
            risk_level=latest.risk_level if latest is not None else None,
            findings=latest.findings if latest is not None else None,
        )

    def latest_completed_scan(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        """The most recent completed scan for a version (the gate's source of risk_level)."""
        return self._scans.latest_completed_for_version(prompt_version_id)

    def latest_scan(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        """The most recent scan for a version, any status (to detect an in-flight scan)."""
        return self._scans.latest_for_version(prompt_version_id)

    # ----------------------------------------------------------------- shared
    def _enqueue_scan(self, prompt_version_id: uuid.UUID) -> SecurityScan:
        """Create a pending scan for a version and hand it to the enqueue side."""
        scan = SecurityScan(prompt_version_id=prompt_version_id, scanners=[], status="pending")
        self._scans.add(scan)
        self._scans.flush()  # populate scan.id before we enqueue it
        self._submit_scan(scan.id)
        _logger.info(
            "scan_enqueued",
            security_scan_id=str(scan.id),
            prompt_version_id=str(prompt_version_id),
        )
        return scan

    def _require_prompt(self, name: str) -> Prompt:
        prompt = self._prompts.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)
        return prompt

    @staticmethod
    def _require_version(prompt: Prompt, name: str, version_number: int) -> PromptVersion:
        version = next((v for v in prompt.versions if v.version_number == version_number), None)
        if version is None:
            raise VersionNotFoundError(name, version_number)
        return version
