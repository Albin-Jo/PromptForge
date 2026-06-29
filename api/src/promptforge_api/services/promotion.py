"""The promotion gate — orchestration around the pure decision rule (Sprint 11 / Phase 8).

This is the I/O half of "eval-on-change": :func:`promotion.decide` is pure policy; this
gate loads the summaries it needs, records the outcome, and fires the webhook. It is
injected into :class:`PromptService`, which still owns moving the label — so the gate
*authorizes* a promotion and *records* it, but the label move stays in one place.

The flow for a move of the **gated label** (``production``):

1. **No golden set** → refuse outright (the prompt has no quality bar; ``GoldenSetMissingError``).
2. **No completed eval for the candidate** → if one is in flight, ask the caller to retry; else
   start one now (the "or promote" trigger) and ask them to retry (``PromotionPending``).
3. **Compare** the candidate's summary against the current production version's via ``decide``.
   - blocked → write a ``blocked`` audit, fire the webhook, return :class:`PromotionBlocked`.
   - allowed → return :class:`GateAllowed`; the prompt service moves the label, then calls
     :meth:`record_promotion` to write the ``promoted`` audit and fire ``promotion.promoted``.

Why blocked/pending are **returned, not raised:** a blocked decision must persist its audit row
and a triggered eval must persist its run, but the request returns a non-2xx. Raising would roll
both back with the request transaction, so these are ordinary return values the router turns into
a 409 (a returned response commits; a raised exception rolls back). Genuine "can't even attempt"
errors (no golden set, unknown prompt/version) still raise.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from promptforge_api.db.models import Label, Prompt, PromptVersion
from promptforge_api.db.promotion_models import PromotionAudit
from promptforge_api.exceptions import GoldenSetMissingError
from promptforge_api.promotion import PromotionPolicy, RunSummary, decide
from promptforge_api.repositories.promotion import PromotionAuditRepository
from promptforge_api.security_gate import SecurityGatePolicy, risk_blocks
from promptforge_api.services.evals import EvalService
from promptforge_api.services.scans import ScanService

_logger = structlog.get_logger(__name__)

# The delivery side: given a built event payload, deliver it (enqueue a webhook task). A no-op
# when no webhook is configured. Taken by injection so the gate never imports Celery.
WebhookSubmit = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class GateAllowed:
    """The gate's "you may promote" — carries the evidence the audit will record."""

    detail: dict[str, Any]


@dataclass(frozen=True)
class PromotionPromoted:
    """Terminal success: the label now points at the candidate."""

    label: Label
    detail: dict[str, Any] | None = None  # gate evidence (None for an ungated label move)


@dataclass(frozen=True)
class PromotionBlocked:
    """Terminal refusal: the candidate is worse / below the bar. Audit + webhook already done."""

    reason: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class PromotionPending:
    """Not-yet-decidable: the candidate's eval *or scan* is in flight (or was just started).

    ``run_id`` is the async job to poll; ``kind`` says which gate it belongs to (``"eval"`` or
    ``"scan"``) so the router can label it for the caller.
    """

    message: str
    run_id: uuid.UUID
    kind: str = "eval"


# What PromptService.set_label hands back to the router.
PromotionResult = PromotionPromoted | PromotionBlocked | PromotionPending


class PromotionGate:
    """Authorizes and records promotions of the gated label, using the eval results."""

    def __init__(
        self,
        evals: EvalService,
        audits: PromotionAuditRepository,
        *,
        policy: PromotionPolicy,
        submit_webhook: WebhookSubmit,
        scans: ScanService | None = None,
        security_policy: SecurityGatePolicy | None = None,
    ) -> None:
        self._evals = evals
        self._audits = audits
        self._policy = policy
        self._submit_webhook = submit_webhook
        # The security gate is optional and independent of the eval gate: without it (or in "warn"
        # mode) label moves aren't safety-blocked. With it in "block" mode, a high-risk scan refuses
        # promotion regardless of the golden set (scanning has no golden-set precondition).
        self._scans = scans
        self._security_policy = security_policy

    @property
    def gated_label(self) -> str:
        """The label whose moves this gate guards (e.g. ``production``)."""
        return self._policy.gated_label

    def trigger_on_create(self, prompt: Prompt, version: PromptVersion) -> None:
        """Eagerly enqueue a gating eval for a just-created version (no-op without a golden set)."""
        self._evals.trigger_on_create(prompt, version)

    def evaluate(
        self,
        *,
        prompt: Prompt,
        candidate: PromptVersion,
        current_version: PromptVersion | None,
        label: str,
        actor: str,
    ) -> GateAllowed | PromotionBlocked | PromotionPending:
        """Decide whether *candidate* may take the gated label; record + notify on a block.

        The **security** gate runs first and independently: a high-risk scan blocks (or, if the
        scan hasn't finished, asks the caller to retry) *before* the eval gate's golden-set
        requirement, so an unsafe candidate is refused even when it has no quality bar configured.
        """
        security = self._security_outcome(prompt, candidate, current_version, label, actor)
        if security is not None:
            return security

        if prompt.golden_set_id is None:
            raise GoldenSetMissingError(prompt.name)

        candidate_run = self._evals.latest_completed_run(candidate.id)
        if candidate_run is None or candidate_run.summary is None:
            in_flight = self._evals.latest_run(candidate.id)
            if in_flight is not None and in_flight.status in ("pending", "running"):
                return PromotionPending(
                    "evaluation in progress; retry once it completes", in_flight.id
                )
            # None, or a previous run failed — start a fresh one (the "or promote" trigger).
            started = self._evals.trigger_on_create(prompt, candidate)
            assert started is not None  # golden_set_id is set (checked above)
            return PromotionPending("evaluation started; retry once it completes", started.id)

        production_run = (
            self._evals.latest_completed_run(current_version.id)
            if current_version is not None
            else None
        )
        production_summary = (
            RunSummary.from_eval_summary(production_run.summary)
            if production_run is not None and production_run.summary is not None
            else None
        )
        decision = decide(
            RunSummary.from_eval_summary(candidate_run.summary), production_summary, self._policy
        )

        detail: dict[str, Any] = {
            **decision.as_detail(),
            "eval_run_id": str(candidate_run.id),
            "candidate_summary": candidate_run.summary,
            "production_eval_run_id": str(production_run.id) if production_run else None,
            "from_version": current_version.version_number if current_version else None,
            "to_version": candidate.version_number,
        }

        if decision.allowed:
            return GateAllowed(detail=detail)

        reason = "; ".join(decision.reasons)
        self._record(prompt, candidate, current_version, label, "blocked", reason, actor, detail)
        self._fire("promotion.blocked", prompt, candidate, current_version, label, reason, detail)
        _logger.warning(
            "promotion_blocked",
            prompt=prompt.name,
            to_version=candidate.version_number,
            reason=reason,
        )
        return PromotionBlocked(reason=reason, detail=detail)

    def _security_outcome(
        self,
        prompt: Prompt,
        candidate: PromptVersion,
        current_version: PromptVersion | None,
        label: str,
        actor: str,
    ) -> PromotionBlocked | PromotionPending | None:
        """Run the security gate: ``None`` to allow, else a block/pending outcome.

        A no-op unless a scan service is wired *and* the policy is in ``block`` mode (the default
        ``warn`` records findings but never blocks). In block mode it needs the candidate's latest
        **completed** scan: if there isn't one yet it returns a scan-pending result (starting a scan
        if none is in flight), mirroring the eval gate's "or promote" trigger.
        """
        if self._scans is None or self._security_policy is None:
            return None
        if self._security_policy.mode != "block":
            return None

        completed = self._scans.latest_completed_scan(candidate.id)
        if completed is None:
            in_flight = self._scans.latest_scan(candidate.id)
            if in_flight is not None and in_flight.status in ("pending", "running"):
                return PromotionPending(
                    "security scan in progress; retry once it completes", in_flight.id, kind="scan"
                )
            started = self._scans.trigger_on_create(prompt, candidate)
            return PromotionPending(
                "security scan started; retry once it completes", started.id, kind="scan"
            )

        if not risk_blocks(completed.risk_level, self._security_policy):
            return None

        reason = (
            f"security scan risk '{completed.risk_level}' is at or above the block threshold "
            f"'{self._security_policy.block_severity.value}'"
        )
        detail: dict[str, Any] = {
            "security": True,
            "risk_level": completed.risk_level,
            "security_scan_id": str(completed.id),
            "findings": completed.findings,
            "from_version": current_version.version_number if current_version else None,
            "to_version": candidate.version_number,
        }
        self._record(prompt, candidate, current_version, label, "blocked", reason, actor, detail)
        self._fire("promotion.blocked", prompt, candidate, current_version, label, reason, detail)
        _logger.warning(
            "promotion_blocked_security",
            prompt=prompt.name,
            to_version=candidate.version_number,
            risk_level=completed.risk_level,
        )
        return PromotionBlocked(reason=reason, detail=detail)

    def record_promotion(
        self,
        *,
        prompt: Prompt,
        candidate: PromptVersion,
        previous: PromptVersion | None,
        label: str,
        actor: str,
        detail: dict[str, Any] | None,
    ) -> None:
        """Write the ``promoted`` audit + fire ``promotion.promoted`` after the label moved."""
        checked = bool(detail and detail.get("regression_checked"))
        reason = (
            "promoted: cleared the quality gate"
            if checked
            else "promoted: cleared the quality floor (regression check skipped — small golden set)"
        )
        self._record(prompt, candidate, previous, label, "promoted", reason, actor, detail or {})
        self._fire("promotion.promoted", prompt, candidate, previous, label, reason, detail or {})
        _logger.info("promotion_succeeded", prompt=prompt.name, to_version=candidate.version_number)

    # ----------------------------------------------------------------- shared
    def _record(
        self,
        prompt: Prompt,
        candidate: PromptVersion,
        previous: PromptVersion | None,
        label: str,
        decision: str,
        reason: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        self._audits.add(
            PromotionAudit(
                prompt_id=prompt.id,
                label=label,
                to_version_id=candidate.id,
                to_version_number=candidate.version_number,
                from_version_id=previous.id if previous is not None else None,
                from_version_number=previous.version_number if previous is not None else None,
                decision=decision,
                reason=reason,
                actor=actor,
                detail=detail,
            )
        )
        self._audits.flush()

    def _fire(
        self,
        event: str,
        prompt: Prompt,
        candidate: PromptVersion,
        previous: PromptVersion | None,
        label: str,
        reason: str,
        detail: dict[str, Any],
    ) -> None:
        self._submit_webhook(
            {
                "event": event,
                "prompt": prompt.name,
                "label": label,
                "to_version": candidate.version_number,
                "from_version": previous.version_number if previous is not None else None,
                "reason": reason,
                "detail": detail,
            }
        )
