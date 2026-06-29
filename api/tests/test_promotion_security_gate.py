"""Unit tests for the security half of the promotion gate (no DB, fakes for the injected services).

Covers the Sprint 12 DoD clause "high-severity can block promotion" at the decision boundary: in
block mode a completed high-risk scan blocks (writing an audit + firing a webhook), an unfinished
scan defers, and a clean/low scan (or warn mode) lets the promotion through. The eval half of the
gate is exercised elsewhere; here the security check returns before any eval logic, so the eval
service is never touched.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Literal

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.promotion import PromotionPolicy
from promptforge_api.scanning import Category, Finding, Severity
from promptforge_api.security_gate import SecurityGatePolicy
from promptforge_api.services.promotion import (
    PromotionBlocked,
    PromotionGate,
    PromotionPending,
)

_POLICY = PromotionPolicy(
    gated_label="production", min_quality=0.7, max_quality_drop=0.05, min_dataset_size=3
)


class _FakeAudits:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, audit: Any) -> None:
        self.added.append(audit)

    def flush(self) -> None:
        pass


class _FakeScans:
    """A stand-in ScanService: serves a preset completed/in-flight scan and records triggers."""

    def __init__(
        self, *, completed: SecurityScan | None = None, in_flight: SecurityScan | None = None
    ) -> None:
        self._completed = completed
        self._in_flight = in_flight
        self.triggered: list[uuid.UUID] = []

    def latest_completed_scan(self, version_id: uuid.UUID) -> SecurityScan | None:
        return self._completed

    def latest_scan(self, version_id: uuid.UUID) -> SecurityScan | None:
        return self._in_flight or self._completed

    def trigger_on_create(self, prompt: Prompt, version: PromptVersion) -> SecurityScan:
        scan = SecurityScan(
            id=uuid.uuid4(), prompt_version_id=version.id, scanners=[], status="pending"
        )
        self.triggered.append(scan.id)
        return scan


def _gate(
    scans: _FakeScans, *, mode: Literal["warn", "block"]
) -> tuple[PromotionGate, list[dict[str, Any]], _FakeAudits]:
    webhooks: list[dict[str, Any]] = []
    audits = _FakeAudits()
    gate = PromotionGate(
        SimpleNamespace(),  # type: ignore[arg-type]  # evals — never reached in these tests
        audits,  # type: ignore[arg-type]
        policy=_POLICY,
        submit_webhook=webhooks.append,
        scans=scans,  # type: ignore[arg-type]
        security_policy=SecurityGatePolicy(mode=mode, block_severity=Severity.HIGH),
    )
    return gate, webhooks, audits


def _candidate() -> tuple[Prompt, PromptVersion]:
    prompt = Prompt(id=uuid.uuid4(), name="greeter")
    version = PromptVersion(id=uuid.uuid4(), version_number=2, content="hi")
    return prompt, version


def _completed_scan(version_id: uuid.UUID, *, risk_level: str) -> SecurityScan:
    finding = Finding(
        category=Category.SECRET,
        severity=Severity.HIGH,
        detector="aws_access_key_id",
        message="key",
        evidence="AKIA…XMPL",
    ).to_dict()
    return SecurityScan(
        id=uuid.uuid4(),
        prompt_version_id=version_id,
        scanners=["secret"],
        status="completed",
        risk_level=risk_level,
        findings=[finding],
    )


def test_block_mode_refuses_promotion_on_high_risk_scan() -> None:
    prompt, candidate = _candidate()
    scans = _FakeScans(completed=_completed_scan(candidate.id, risk_level="high"))
    gate, webhooks, audits = _gate(scans, mode="block")

    outcome = gate.evaluate(
        prompt=prompt, candidate=candidate, current_version=None, label="production", actor="me"
    )

    assert isinstance(outcome, PromotionBlocked)
    assert "high" in outcome.reason
    assert outcome.detail["risk_level"] == "high"
    assert outcome.detail["security"] is True
    assert len(audits.added) == 1  # a 'blocked' audit was written
    assert webhooks and webhooks[0]["event"] == "promotion.blocked"  # and a webhook fired


def test_block_mode_defers_when_scan_still_in_flight() -> None:
    prompt, candidate = _candidate()
    in_flight = SecurityScan(
        id=uuid.uuid4(), prompt_version_id=candidate.id, scanners=[], status="running"
    )
    gate, webhooks, _ = _gate(_FakeScans(in_flight=in_flight), mode="block")

    outcome = gate.evaluate(
        prompt=prompt, candidate=candidate, current_version=None, label="production", actor="me"
    )

    assert isinstance(outcome, PromotionPending)
    assert outcome.kind == "scan"
    assert outcome.run_id == in_flight.id
    assert webhooks == []  # pending is not a decision — nothing recorded/sent


def test_block_mode_starts_a_scan_when_none_exists() -> None:
    prompt, candidate = _candidate()
    scans = _FakeScans()  # no completed, no in-flight
    gate, _, _ = _gate(scans, mode="block")

    outcome = gate.evaluate(
        prompt=prompt, candidate=candidate, current_version=None, label="production", actor="me"
    )

    assert isinstance(outcome, PromotionPending)
    assert outcome.kind == "scan"
    assert scans.triggered == [outcome.run_id]  # a fresh scan was kicked off


def test_block_mode_allows_a_clean_scan_through_security() -> None:
    # A 'none' risk scan must not block — _security_outcome returns None so the gate proceeds.
    prompt, candidate = _candidate()
    scans = _FakeScans(completed=_completed_scan(candidate.id, risk_level="none"))
    gate, _, _ = _gate(scans, mode="block")

    assert gate._security_outcome(prompt, candidate, None, "production", "me") is None


def test_warn_mode_never_blocks_on_security() -> None:
    prompt, candidate = _candidate()
    scans = _FakeScans(completed=_completed_scan(candidate.id, risk_level="high"))
    gate, _, _ = _gate(scans, mode="warn")

    # Even a high-risk scan is a no-op for the security gate in warn mode.
    assert gate._security_outcome(prompt, candidate, None, "production", "me") is None
