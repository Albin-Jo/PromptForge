"""The pluggable scoring interface — the seam the whole eval engine is built on.

A *scorer* answers one question about a single model output: *how good is it, and
why?* Different scorers answer it differently — an LLM judge (this sprint), an
exact-match or regex check, an embedding-similarity score (later) — but the eval
engine should drive them all through one shape and never branch on which kind it
holds. That shape is :class:`Scorer`.

Two deliberate choices (ADR 0010):

- **It's a** :class:`typing.Protocol`, **not an ABC.** Structural typing: a class
  *is* a ``Scorer`` if it has a matching ``name`` and ``score`` — it neither
  imports nor subclasses anything here. New scorers stay decoupled from this
  module, the same spirit as keeping dataclasses (not Pydantic) inside the domain.
- **``score`` is** ``async``. The flagship scorer awaits the async LLM gateway, so
  the interface is async across the board; a synchronous scorer (exact match) just
  doesn't ``await`` anything. A uniform signature lets the engine ``await`` every
  scorer the same way.

:class:`Score` is the output — a plain frozen dataclass, produced inside the trusted
core, so no Pydantic here (CLAUDE.md: Pydantic at the boundary, dataclasses inside).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Score:
    """One scorer's verdict on one output.

    - ``value`` — a normalised quality score in ``[0.0, 1.0]`` (1.0 = best), so
      verdicts from *different* scorers are aggregated on one comparable scale.
    - ``passed`` — the boolean gate, derived by the scorer from ``value`` against
      its own threshold. This is what eval-on-change (Sprint 11) will key promotion
      off, kept separate from ``value`` so "how good" and "good enough?" don't
      conflate.
    - ``rationale`` — the human-readable *why*. The point of an LLM judge over a
      bare number: a reviewer can read the reasoning and trust (or distrust) it.
    - ``metadata`` — scorer-specific extras (the judge's raw rating, the model used,
      token usage…). Free-form on purpose; never load-bearing for control flow.
    """

    value: float
    passed: bool
    rationale: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Scorer(Protocol):
    """Anything that can grade one output. Implementations need not inherit this.

    ``name`` is a stable identifier recorded on every :class:`Score`'s eval run, so
    a stored result always says *which* scorer produced it.
    """

    name: str

    async def score(
        self,
        *,
        input: str,
        output: str,
        reference: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Score:
        """Grade ``output``.

        - ``input`` — what the model was asked (the prompt's rendered input). Gives
          the scorer the question, so relevance/faithfulness can be judged in context.
        - ``output`` — the actual model output under test. The thing being graded.
        - ``reference`` — an optional gold/expected answer. Present for
          *reference-based* scoring (compare against truth); ``None`` for
          *reference-free* scoring (judge intrinsic quality against criteria).
        - ``context`` — optional extras a scorer may use: grading ``criteria``,
          retrieved documents for a RAG faithfulness check, etc. Scorer-defined keys.
        """
        ...
