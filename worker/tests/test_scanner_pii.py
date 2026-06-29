"""Fixture tests for the PII scanner — malicious + clean, asserting precision on the clean set.

The clean corpus carries the things that fool naive PII regexes: an order id (not a card), a
version string (not an IP), a UUID, a non-Luhn 16-digit run. They must all produce zero findings.
The malicious corpus carries one real-shaped PII item each, flagged with the right detector and
severity.
"""

from __future__ import annotations

import pytest

from promptforge_api.scanning import Category, Severity
from promptforge_worker.scanning.pii_scanner import PIIScanner, _luhn_valid, _valid_ssn

# (text, expected detector, expected severity)
_MALICIOUS: list[tuple[str, str, Severity]] = [
    ("Contact me at jane.doe@example.com please.", "email_address", Severity.MEDIUM),
    ("My SSN is 123-45-6789, please don't share.", "us_ssn", Severity.HIGH),
    ("Card on file: 4111 1111 1111 1111", "credit_card", Severity.HIGH),
    ("Call me at 415-555-2671 tomorrow.", "phone_number", Severity.LOW),
]

# Benign prompts that must produce ZERO findings (the precision bar).
_CLEAN: list[str] = [
    "Summarise the customer's order history in a friendly tone.",
    "Order #100245 shipped on the 3rd; reference it in the reply.",
    "Use semantic version 1.2.3.4 in the changelog header.",
    "Reference id: 550e8400-e29b-41d4-a716-446655440000 in the ticket.",
    "Internal tracking number 4111111111111112 is not a card.",  # card-shaped, fails Luhn
    "Placeholder code 000-12-3456 in the docs.",  # SSN-shaped but invalid area → not flagged
    "Reply within 24 hours to the support queue.",
]


@pytest.mark.parametrize(("text", "detector", "severity"), _MALICIOUS)
async def test_flags_known_pii(text: str, detector: str, severity: Severity) -> None:
    findings = await PIIScanner().scan(text=text)
    matched = [f for f in findings if f.detector == detector]
    assert matched, f"expected a {detector} finding in {text!r}, got {findings}"
    assert matched[0].severity == severity
    assert matched[0].category == Category.PII


@pytest.mark.parametrize("text", _CLEAN)
async def test_clean_text_has_no_findings(text: str) -> None:
    assert await PIIScanner().scan(text=text) == []


async def test_email_evidence_is_masked() -> None:
    findings = await PIIScanner().scan(text="reach me: alice@corp.io")
    assert findings[0].detector == "email_address"
    assert findings[0].evidence == "a***@corp.io"
    assert "alice" not in findings[0].evidence


async def test_ssn_evidence_keeps_only_last_four() -> None:
    findings = await PIIScanner().scan(text="ssn 123-45-6789")
    assert findings[0].evidence == "***-**-6789"


async def test_card_evidence_keeps_only_last_four() -> None:
    findings = await PIIScanner().scan(text="4111111111111111")
    assert findings[0].detector == "credit_card"
    assert findings[0].evidence == "************1111"


def test_luhn_accepts_valid_and_rejects_invalid() -> None:
    assert _luhn_valid("4111111111111111")  # Visa test number
    assert not _luhn_valid("4111111111111112")  # same, checksum digit bumped


def test_invalid_ssn_ranges_are_rejected() -> None:
    assert not _valid_ssn("000", "12", "3456")
    assert not _valid_ssn("666", "12", "3456")
    assert not _valid_ssn("900", "12", "3456")
    assert not _valid_ssn("123", "00", "3456")
    assert _valid_ssn("123", "45", "6789")
