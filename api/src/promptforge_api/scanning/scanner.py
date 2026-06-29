"""The pluggable scanner interface — the seam the whole scanning engine is built on.

A *scanner* answers one question about a piece of prompt text: *what safety problems does it
carry, and where?* Different scanners answer differently — regex + entropy for secrets, regex
(+ optional NER) for PII, a signature set for jailbreaks, heuristics + an LLM judge for
injection — but the runner should drive them all through one shape and never branch on which
kind it holds. That shape is :class:`Scanner`.

This deliberately mirrors :class:`~promptforge_api.evals.scorer.Scorer` (ADR 0010):

- **It's a** :class:`typing.Protocol`, **not an ABC.** Structural typing: a class *is* a
  ``Scanner`` if it has a matching ``name``, ``category``, and ``scan`` — it neither imports nor
  subclasses anything here, so new scanners stay decoupled from this module.
- **``scan`` is** ``async``. The injection scanner awaits the async LLM gateway, so the
  interface is async across the board; a purely synchronous scanner (regex/entropy) just doesn't
  ``await`` anything. A uniform signature lets the runner ``await`` every scanner the same way.
"""

from typing import Protocol

from promptforge_api.scanning.finding import Category, Finding


class Scanner(Protocol):
    """Anything that can scan text for one family of safety problem.

    Implementations need not inherit this.

    - ``name`` — stable identifier recorded on the scan (which scanners ran), e.g.
      ``"secret"``, ``"injection"``. Lets a stored scan say exactly how it was checked.
    - ``category`` — the :class:`Category` every finding from this scanner belongs to.
    """

    name: str
    category: Category

    async def scan(self, *, text: str) -> list[Finding]:
        """Inspect ``text`` and return zero or more :class:`Finding`s.

        An empty list means "clean by this scanner" — a positive statement, not an error.
        Implementations must not raise on benign input; a malformed *internal* failure
        (e.g. the LLM judge being unreachable) is the runner's concern, not a finding.
        """
        ...
