"""The PII scanner — structured-PII regexes, with a seam for an NER pass later.

PII detection splits cleanly in two: *structured* PII has a fixed shape regex nails with high
precision (emails, US SSNs, credit-card numbers, phone numbers); *unstructured* PII (person names,
locations, organisations) needs an NER model to recognise. v0.1 ships the structured half only —
it covers the cases that matter most for a prompt-safety signal and keeps the worker image lean
(ADR/decision: regex-only for v0.1, NER as a backlog item). The :meth:`_ner_findings` hook below is
the documented seam where a spaCy/Presidio recogniser drops in without touching the rest.

Precision choices (the sprint's open-ended risk is false positives):

- **Credit cards are Luhn-validated** — a 13–19 digit run that fails the checksum is almost
  certainly an order id, not a card, so we don't flag it.
- **SSNs reject structurally-invalid ranges** (area 000/666/900+, zero group/serial).
- **IPv4 is intentionally omitted** — it's only marginal PII and collides with version strings
  ("1.2.3.4"), which would wreck precision (backlog).

Severity follows sensitivity: card/SSN HIGH, email MEDIUM, phone LOW. Evidence is partially
masked — PII is sensitive too, so a finding stores ``j***@example.com`` / ``***-**-6789``, never
the full value.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from promptforge_api.gateway import LLMGateway
from promptforge_api.scanning import Category, Finding, Severity
from promptforge_worker.scanning.registry import register

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
# US/NANP-ish phone: optional +1, area code, then 3-4 with separators required (a bare 10-digit
# run is too ambiguous to flag). Separators keep this from matching arbitrary number sequences.
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s](\d{4})\b")
# A 13–19 digit run, optionally grouped by single spaces/dashes — Luhn-checked before flagging.
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_valid(digits: str) -> bool:
    """The Luhn checksum every real card number satisfies — our credit-card precision guard."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _valid_ssn(area: str, group: str, serial: str) -> bool:
    """Reject SSN-shaped numbers in ranges the SSA never issues (cuts false positives)."""
    if area in {"000", "666"} or area[0] == "9":
        return False
    return group != "00" and serial != "0000"


def _mask_tail(value: str, visible: int = 4) -> str:
    """Mask all but the last *visible* characters of a numeric PII value."""
    return ("*" * max(0, len(value) - visible)) + value[-visible:]


class PIIScanner:
    """Flags structured PII (email, SSN, credit card, phone) in prompt text."""

    name = "pii"
    category = Category.PII

    async def scan(self, *, text: str) -> list[Finding]:
        """Return one finding per detected PII item, across all detectors plus the NER seam."""
        findings: list[Finding] = []
        findings.extend(self._email_findings(text))
        findings.extend(self._ssn_findings(text))
        findings.extend(self._card_findings(text))
        findings.extend(self._phone_findings(text))
        findings.extend(self._ner_findings(text))
        return findings

    def _email_findings(self, text: str) -> Iterator[Finding]:
        for match in _EMAIL.finditer(text):
            local, _, domain = match.group(0).partition("@")
            yield self._finding(
                Severity.MEDIUM,
                "email_address",
                "Possible email address",
                evidence=f"{local[0]}***@{domain}",
                span=match.span(),
            )

    def _ssn_findings(self, text: str) -> Iterator[Finding]:
        for match in _SSN.finditer(text):
            area, group, serial = match.group(1), match.group(2), match.group(3)
            if not _valid_ssn(area, group, serial):
                continue
            yield self._finding(
                Severity.HIGH,
                "us_ssn",
                "Possible US Social Security Number",
                evidence=f"***-**-{serial}",
                span=match.span(),
            )

    def _card_findings(self, text: str) -> Iterator[Finding]:
        for match in _CARD.finditer(text):
            digits = re.sub(r"[ -]", "", match.group(0))
            if not _luhn_valid(digits):
                continue
            yield self._finding(
                Severity.HIGH,
                "credit_card",
                "Possible credit-card number",
                evidence=_mask_tail(digits),
                span=match.span(),
            )

    def _phone_findings(self, text: str) -> Iterator[Finding]:
        for match in _PHONE.finditer(text):
            yield self._finding(
                Severity.LOW,
                "phone_number",
                "Possible phone number",
                evidence=f"***-***-{match.group(1)}",
                span=match.span(),
            )

    def _ner_findings(self, text: str) -> Iterator[Finding]:
        """Seam for unstructured PII (names/locations/orgs) via NER — empty in v0.1 (backlog).

        A future spaCy/Presidio recogniser yields :class:`Finding`s here; the rest of the scanner
        is already shaped to collect them, so adding NER touches only this method + a dependency.
        """
        return iter(())

    def _finding(
        self,
        severity: Severity,
        detector: str,
        message: str,
        *,
        evidence: str,
        span: tuple[int, int],
    ) -> Finding:
        return Finding(
            category=self.category,
            severity=severity,
            detector=detector,
            message=message,
            evidence=evidence,
            span=span,
        )


@register
def _build(_gateway: LLMGateway) -> PIIScanner:
    """Registry factory: the PII scanner needs no gateway (pure regex)."""
    return PIIScanner()
