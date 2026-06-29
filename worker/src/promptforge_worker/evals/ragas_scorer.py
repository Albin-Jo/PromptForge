"""A RAGAS scorer behind the API's ``Scorer`` Protocol — reference-based factual correctness.

We wrap RAGAS's **FactualCorrectness** metric: it decomposes the model's output into atomic
claims and checks each against the reference answer with an NLI step, returning a precision/
recall/f1 in ``[0,1]``. It's *reference-based* (needs the gold answer) and LLM-only (no
embeddings — our gateway is chat-only), which is exactly why it was chosen over RAGAS's
embedding- or retrieval-context-dependent metrics (Sprint 8 decision). It complements the
from-scratch ``LLMJudgeScorer``, which is reference-*free* — two different signals on one run.

**Why the deprecated import path.** RAGAS 0.4.x is mid-migration: the future ``collections``
``FactualCorrectness`` requires an ``instructor``-based client we can't point at our gateway,
while the legacy ``ragas.metrics`` one accepts a ``BaseRagasLLM`` we *can* (see
:mod:`gateway_llm`). So we deliberately use the legacy metric and suppress its deprecation
warning here. Migrating to the ``collections`` API is parked in the learning backlog for when
RAGAS 1.0 forces it. RAGAS exposes only a numeric score (no reasoning), so the ``rationale`` is
synthesised — an honest asymmetry versus the judge/GEval, which return real explanations.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

import structlog

from promptforge_api.evals.scorer import Score
from promptforge_api.gateway import LLMGateway
from promptforge_worker.evals.gateway_llm import GatewayRagasLLM

with warnings.catch_warnings():
    # The legacy import path is deliberate (see module docstring); don't let its
    # DeprecationWarning spam the worker logs on every import.
    warnings.simplefilter("ignore", DeprecationWarning)
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics import FactualCorrectness

_logger = structlog.get_logger(__name__)

# Default gate for the f1 score. Coarser than the judge's because claim-level f1 is a stricter
# measure — a single missed claim drops it noticeably; tune per scorer via the run config.
_DEFAULT_PASS_THRESHOLD = 0.5


class RagasFactualCorrectnessError(ValueError):
    """Raised when the scorer is asked to grade an item it structurally can't."""


class RagasFactualCorrectnessScorer:
    """Grades factual correctness of an output against a reference, via RAGAS.

    Conforms structurally to :class:`promptforge_api.evals.scorer.Scorer`. The gateway is
    injected, as with the judge — the metric's internal LLM calls go through it (no vendor SDK).
    """

    name = "ragas_factual_correctness"

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        model: str = "openai/gpt-4o-mini",
        pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
        mode: str = "f1",
    ) -> None:
        """Wire the metric to a gateway and its grading policy.

        ``mode`` selects which of RAGAS's precision/recall/f1 the metric reports; ``f1`` (the
        balance of the two) is the sensible default. ``pass_threshold`` is the ``[0,1]`` gate
        for ``passed`` — platform policy, not RAGAS's (mirrors the judge).
        """
        self._gateway = gateway
        self._model = model
        self._pass_threshold = pass_threshold
        self._mode = mode

    async def score(
        self,
        *,
        input: str,
        output: str,
        reference: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Score:
        """Score ``output``'s factual correctness against ``reference``.

        Raises :class:`RagasFactualCorrectnessError` when ``reference`` is missing — this
        metric is reference-based and has nothing to grade against without one. The eval
        runner decides whether to skip such items or fail the run (Sprint 8 chunk 3).
        """
        if reference is None or not reference.strip():
            raise RagasFactualCorrectnessError(
                "ragas_factual_correctness is reference-based; the item has no reference answer"
            )

        # A fresh metric per call: it binds the gateway-backed LLM and carries no cross-item
        # state, so there's nothing to reuse and per-call construction keeps it stateless.
        metric = FactualCorrectness(
            llm=GatewayRagasLLM(self._gateway, model=self._model),
            mode=self._mode,
        )
        sample = SingleTurnSample(user_input=input, response=output, reference=reference)

        _logger.info("ragas_scoring_started", metric=self.name, mode=self._mode, model=self._model)
        raw = await metric.single_turn_ascore(sample)
        value = float(raw)
        passed = value >= self._pass_threshold

        _logger.info("ragas_scoring_finished", metric=self.name, value=value, passed=passed)
        return Score(
            value=value,
            passed=passed,
            # RAGAS returns only a number; synthesise a rationale so the field is never empty,
            # and flag in metadata that it isn't a model-written explanation (unlike the judge).
            rationale=(
                f"RAGAS FactualCorrectness ({self._mode}) = {value:.3f}: the output's claims "
                f"were decomposed and checked against the reference answer."
            ),
            metadata={
                "scorer": self.name,
                "metric_model": self._model,
                "mode": self._mode,
                "pass_threshold": self._pass_threshold,
                "rationale_synthetic": True,
            },
        )
