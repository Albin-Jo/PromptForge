"""Fixture tests for the secret-leakage scanner.

The DoD's testing clause for scanners: known-malicious and known-clean fixtures per scanner,
*asserting precision on the clean set* (no false positives on benign prompts). The clean corpus
deliberately includes the things that trip naive secret scanners — template variables, placeholder
example keys, a git SHA, a UUID — and must produce zero findings. The malicious corpus carries one
real-format credential each and must be flagged with the right detector and severity.
"""

from __future__ import annotations

import pytest

from promptforge_api.scanning import Category, Severity
from promptforge_worker.scanning.secret_scanner import (
    SecretScanner,
    _is_placeholder,
    _shannon_entropy,
)

# Synthetic secret fixtures — NOT live credentials (each is a public documentation
# example or a randomly-shaped token). They're realistic enough that upstream secret
# scanners (incl. GitHub push protection) flag them if the full token appears as a
# contiguous literal, so we assemble each from prefix + body: the verbatim token never
# exists in source, while the scanner under test still receives the reconstructed
# string at runtime. The AWS key is reused by the redaction/dedup tests below.
_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
_GITHUB_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_OPENAI_KEY = "sk-" + "abcdefABCDEF0123456789xyzQRS"
_GOOGLE_KEY = "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"
_SLACK_TOKEN = "xoxb-" + "1234567890-abcdefXYZ098"
_STRIPE_KEY = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"

# (text, expected detector, expected severity) — each carries exactly one planted secret.
_MALICIOUS: list[tuple[str, str, Severity]] = [
    (f"AWS_ACCESS_KEY_ID={_AWS_KEY}", "aws_access_key_id", Severity.HIGH),
    (f"token: {_GITHUB_TOKEN}", "github_token", Severity.HIGH),
    (f"openai key {_OPENAI_KEY}", "openai_api_key", Severity.HIGH),
    (f"google = {_GOOGLE_KEY}", "google_api_key", Severity.HIGH),
    (f"slack {_SLACK_TOKEN}", "slack_token", Severity.HIGH),
    (f"stripe {_STRIPE_KEY}", "stripe_secret_key", Severity.HIGH),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...", "private_key", Severity.HIGH),
    ('password = "Xk9mP2vLq8wRtYzB"', "high_entropy_assignment", Severity.MEDIUM),
]

# Benign prompts that must produce ZERO findings (the precision bar).
_CLEAN: list[str] = [
    "Summarise the following article in three sentences.",
    "Authenticate using the API key {{api_key}} provided by the caller.",
    'Set api_key = "your-api-key-here" before running the example.',
    "password: changeme",
    'auth_token = "<YOUR_TOKEN>"',
    "See commit a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4 for the fix.",
    "Reference id: 550e8400-e29b-41d4-a716-446655440000 in the ticket.",
    'Use model = "gpt-4o-mini" with a temperature of 0.2.',
    "Let's talk about your skills and experience.",
    'username = "john_doe"',
]


@pytest.mark.parametrize(("text", "detector", "severity"), _MALICIOUS)
async def test_flags_known_secret(text: str, detector: str, severity: Severity) -> None:
    findings = await SecretScanner().scan(text=text)
    matched = [f for f in findings if f.detector == detector]
    assert matched, f"expected a {detector} finding in {text!r}, got {findings}"
    assert matched[0].severity == severity
    assert matched[0].category == Category.SECRET


@pytest.mark.parametrize("text", _CLEAN)
async def test_clean_text_has_no_findings(text: str) -> None:
    # Precision bar: a benign prompt must not produce a single finding.
    assert await SecretScanner().scan(text=text) == []


async def test_evidence_is_redacted_never_the_raw_secret() -> None:
    secret = _AWS_KEY
    findings = await SecretScanner().scan(text=f"key={secret}")
    assert findings, "expected the AWS key to be flagged"
    evidence = findings[0].evidence
    assert secret not in evidence  # the live secret is never stored
    assert "…" in evidence  # but a masked head/tail is kept for triage


async def test_private_key_evidence_does_not_echo_the_body() -> None:
    findings = await SecretScanner().scan(text="-----BEGIN PRIVATE KEY-----\nMIIEvQ...")
    assert findings[0].detector == "private_key"
    assert "MIIEvQ" not in findings[0].evidence


async def test_overlapping_named_and_entropy_match_is_deduped() -> None:
    # api_key = AKIA… would match both the AWS rule and the entropy fallback; only the high-
    # confidence named finding should survive.
    findings = await SecretScanner().scan(text=f'api_key = "{_AWS_KEY}"')
    assert len(findings) == 1
    assert findings[0].detector == "aws_access_key_id"


def test_shannon_entropy_orders_random_above_repetitive() -> None:
    assert _shannon_entropy("aaaaaaaa") < _shannon_entropy("Xk9mP2vLq8wRtYzB")
    assert _shannon_entropy("") == 0.0


def test_placeholder_detection() -> None:
    assert _is_placeholder("your-api-key-here")
    assert _is_placeholder("{{secret}}")
    assert _is_placeholder("xxxxxxxx")
    assert not _is_placeholder("Xk9mP2vLq8wRtYzB")
