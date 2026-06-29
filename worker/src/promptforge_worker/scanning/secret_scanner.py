"""The secret-leakage scanner — regex for known credential formats + an entropy fallback.

The most deterministic of the four scanners, so it's the first real one and the easiest to keep
*precise* (the sprint's open-ended risk is false positives, so precision on benign text is the bar
we test against). It works in two layers:

1. **Named rules.** High-confidence regexes for canonical provider credentials — AWS keys, GitHub
   PATs, OpenAI/Google/Slack/Stripe keys, PEM private-key blocks, JWTs. A match here is almost
   never a false positive, so these are HIGH (JWTs MEDIUM — they're often short-lived/non-secret).

2. **Entropy fallback.** For secrets without a fixed format, look only at values *assigned to a
   secret-ish key* (``password = "…"``, ``api_key: "…"``) and flag one when its Shannon entropy is
   high enough to look random — after rejecting template placeholders (``{{var}}``) and obvious
   stand-ins (``your-key-here``). MEDIUM, because this layer is the noisy one; the keyword + entropy
   + placeholder guards keep it from firing on ordinary prose. Standalone high-entropy tokens
   (hashes, UUIDs, git SHAs) are deliberately *not* flagged — they'd wreck precision (backlog).

**Redaction is non-negotiable.** A finding's ``evidence`` is always masked (``AKIA…XMPL``); we never
copy a live secret into our own database — the whole point of not storing the scanned text.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass

from promptforge_api.gateway import LLMGateway
from promptforge_api.scanning import Category, Finding, Severity
from promptforge_worker.scanning.registry import register


@dataclass(frozen=True)
class _Rule:
    """One named-credential regex; ``group`` picks the secret capture (0 = whole match)."""

    detector: str
    pattern: re.Pattern[str]
    severity: Severity
    message: str
    group: int = 0


# High-confidence provider-credential formats. Anchored with \b (or unambiguous prefixes) so they
# don't match mid-token. Ordered most-specific first; overlaps are de-duplicated by span later.
_NAMED_RULES: list[_Rule] = [
    _Rule(
        "aws_access_key_id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        Severity.HIGH,
        "Possible AWS access key id",
    ),
    _Rule(
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
        Severity.HIGH,
        "Possible GitHub access token",
    ),
    _Rule(
        "openai_api_key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        Severity.HIGH,
        "Possible OpenAI API key",
    ),
    _Rule(
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        Severity.HIGH,
        "Possible Google API key",
    ),
    _Rule(
        "slack_token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        Severity.HIGH,
        "Possible Slack token",
    ),
    _Rule(
        "stripe_secret_key",
        re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
        Severity.HIGH,
        "Possible Stripe live secret key",
    ),
    _Rule(
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        Severity.HIGH,
        "Possible private key block",
    ),
    _Rule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        Severity.MEDIUM,
        "Possible JSON Web Token (JWT)",
    ),
]

# The entropy fallback only looks at values assigned to a secret-ish key, captured as group 1.
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret"
    r"|auth(?:[_-]?token)?|bearer)\b[\"']?\s*[:=]\s*[\"']?([^\s\"'`]{8,})"
)

# Substrings that mark a value as an obvious placeholder, not a real secret. Cheap, high-value
# precision guard — these are what benign prompts/examples actually contain.
_PLACEHOLDER_MARKERS = (
    "your",
    "example",
    "changeme",
    "change_me",
    "placeholder",
    "redacted",
    "dummy",
    "sample",
    "test",
    "xxx",
    "...",
    "<",
    ">",
    "{{",
    "}}",
    "_here",
)

# Entropy (bits/char) and length above which an assigned value looks random enough to be a secret.
# Tuned for precision: ordinary words/identifiers fall below ~3.2, real secrets above.
_ENTROPY_THRESHOLD = 3.2
_ENTROPY_MIN_LENGTH = 12


def _shannon_entropy(value: str) -> float:
    """Bits of Shannon entropy per character — a measure of how 'random' a string looks."""
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _is_placeholder(value: str) -> bool:
    """True if the value is an obvious stand-in (template var, ``your-key-here``, repeated char)."""
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    # A single repeated character ("aaaaaaaa") is never a real secret.
    return len(set(value)) <= 1


def _redact(value: str) -> str:
    """Mask a secret for safe storage in a finding: keep a few edge chars, hide the middle."""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


class SecretScanner:
    """Flags leaked credentials in prompt text via named regexes + an entropy fallback."""

    name = "secret"
    category = Category.SECRET

    async def scan(self, *, text: str) -> list[Finding]:
        """Return one finding per detected secret, de-duplicated by overlapping span."""
        findings: list[Finding] = []
        occupied: list[tuple[int, int]] = []

        for finding, span in self._named_findings(text):
            findings.append(finding)
            occupied.append(span)

        for finding, span in self._entropy_findings(text):
            # Skip a value already covered by a higher-confidence named rule (e.g. api_key = AKIA…).
            if not _overlaps_any(span, occupied):
                findings.append(finding)
                occupied.append(span)

        return findings

    def _named_findings(self, text: str) -> Iterator[tuple[Finding, tuple[int, int]]]:
        for rule in _NAMED_RULES:
            for match in rule.pattern.finditer(text):
                span = match.span(rule.group)
                secret = match.group(rule.group)
                # A private-key block's body is multi-line and irrelevant to triage — label it
                # rather than echoing any of it; other rules show a redacted head/tail.
                evidence = (
                    "-----BEGIN … PRIVATE KEY-----"
                    if rule.detector == "private_key"
                    else _redact(secret)
                )
                yield (
                    Finding(
                        category=self.category,
                        severity=rule.severity,
                        detector=rule.detector,
                        message=rule.message,
                        evidence=evidence,
                        span=span,
                    ),
                    span,
                )

    def _entropy_findings(self, text: str) -> Iterator[tuple[Finding, tuple[int, int]]]:
        for match in _ASSIGNMENT.finditer(text):
            value = match.group(1)
            span = match.span(1)
            if len(value) < _ENTROPY_MIN_LENGTH or _is_placeholder(value):
                continue
            entropy = _shannon_entropy(value)
            if entropy < _ENTROPY_THRESHOLD:
                continue
            yield (
                Finding(
                    category=self.category,
                    severity=Severity.MEDIUM,
                    detector="high_entropy_assignment",
                    message="Possible secret assigned to a credential-like field",
                    evidence=_redact(value),
                    span=span,
                    metadata={"entropy": round(entropy, 2)},
                ),
                span,
            )


def _overlaps_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    """True if *span* overlaps any span already recorded (half-open interval overlap)."""
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in spans)


@register
def _build(_gateway: LLMGateway) -> SecretScanner:
    """Registry factory: the secret scanner needs no gateway (pure regex/entropy)."""
    return SecretScanner()
