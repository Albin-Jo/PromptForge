"""The jailbreak scanner — a signature set for known safety-bypass patterns.

Jailbreaks are the *recognisable* attempts to strip a model's safety behaviour: named personas
("DAN / Do Anything Now", "STAN"), and the idiomatic phrasings that ask a model to drop its
guidelines ("ignore your safety guidelines", "you have no restrictions", "pretend to be an
unfiltered AI"). Because these are *known shapes*, a curated signature set catches them with high
precision — which is the whole job here.

Deliberately scoped against the **injection** scanner (task 12) so the two don't double-count:
jailbreak owns *safety-removal / persona-override* signatures; injection owns *instruction-override
and prompt-extraction* ("ignore previous instructions", "reveal your system prompt") via heuristics
+ an LLM judge. So "ignore previous instructions" is **not** a jailbreak signature here.

Precision over recall (the sprint's open-ended risk): every pattern is a multi-word phrase that is
rarely benign. A bare ``developer mode`` rule is intentionally omitted — it collides with legitimate
requests ("enable developer mode in VS Code"). Severity: unambiguous persona/override signatures are
HIGH; weaker single-signal phrasings ("jailbreak", "no ethical guidelines") are MEDIUM. Evidence is
the matched phrase (not sensitive), truncated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from promptforge_api.gateway import LLMGateway
from promptforge_api.scanning import Category, Finding, Severity
from promptforge_worker.scanning.registry import register


@dataclass(frozen=True)
class _Signature:
    """One jailbreak signature: a case-insensitive phrase pattern and how bad a match is."""

    detector: str
    pattern: re.Pattern[str]
    severity: Severity
    message: str


def _ci(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Curated, high-precision signatures. Each is idiomatic to jailbreak prompts and rarely benign.
_SIGNATURES: list[_Signature] = [
    _Signature(
        "do_anything_now",
        _ci(r"\bdo anything now\b|\bDAN\s+mode\b"),
        Severity.HIGH,
        "Known 'DAN / Do Anything Now' jailbreak persona",
    ),
    _Signature(
        "ignore_safety_guidelines",
        _ci(
            r"ignore (?:all )?(?:your |the )?(?:safety|ethical|content|moral)\s+"
            r"(?:guidelines|policy|policies|rules|filters|constraints)"
        ),
        Severity.HIGH,
        "Instruction to ignore safety/content guidelines",
    ),
    _Signature(
        "no_restrictions_persona",
        _ci(
            r"you (?:are|will be|have)(?: now)?(?: an?)?\s+"
            r"(?:no |without )?(?:unrestricted|unfiltered|jailbroken)\b"
            r"|you have no (?:restrictions|filters|rules|limits|guidelines)"
        ),
        Severity.HIGH,
        "Prompt asserts the model has no safety restrictions",
    ),
    _Signature(
        "pretend_unrestricted",
        _ci(
            r"pretend (?:you are|to be) (?:an? )?(?:unrestricted|unfiltered|evil|amoral|jailbroken)"
            r"|as an AI (?:with no|without) (?:restrictions|rules|filters|guidelines)"
        ),
        Severity.HIGH,
        "Roleplay request to act as an unrestricted AI",
    ),
    _Signature(
        "no_ethical_constraints",
        _ci(
            r"(?:with )?no (?:ethical|moral) (?:guidelines|constraints|restrictions|rules)"
            r"|without any (?:filters|censorship)"
        ),
        Severity.MEDIUM,
        "Request to drop ethical/moral constraints",
    ),
    _Signature(
        "jailbreak_mention",
        _ci(r"\bjailbreak(?:ed|ing)?\b|\bjailbroken\b"),
        Severity.MEDIUM,
        "Explicit mention of 'jailbreak'",
    ),
]

_SNIPPET_MAX = 80


def _snippet(text: str) -> str:
    """The matched phrase, whitespace-collapsed and truncated for a tidy finding."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= _SNIPPET_MAX else collapsed[: _SNIPPET_MAX - 1] + "…"


class JailbreakScanner:
    """Flags known jailbreak / safety-bypass signatures in prompt text."""

    name = "jailbreak"
    category = Category.JAILBREAK

    async def scan(self, *, text: str) -> list[Finding]:
        """Return one finding per distinct signature that matches (first match of each)."""
        findings: list[Finding] = []
        for signature in _SIGNATURES:
            match = signature.pattern.search(text)
            if match is None:
                continue
            findings.append(
                Finding(
                    category=self.category,
                    severity=signature.severity,
                    detector=signature.detector,
                    message=signature.message,
                    evidence=_snippet(match.group(0)),
                    span=match.span(),
                )
            )
        return findings


@register
def _build(_gateway: LLMGateway) -> JailbreakScanner:
    """Registry factory: the jailbreak scanner needs no gateway (pure signatures)."""
    return JailbreakScanner()
