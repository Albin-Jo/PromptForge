"""A DeepEval scorer behind the API's ``Scorer`` Protocol — G-Eval criteria grading.

We wrap DeepEval's **GEval**: a flexible LLM-judge that grades against a free-text *criteria*
by first generating its own evaluation steps (chain-of-thought) and then scoring against them,
returning a value in ``[0,1]`` **and a reason**. It's LLM-only (no embeddings) and maps almost
one-to-one onto our :class:`Score` — ``value`` = GEval's score, ``passed`` = score ≥ threshold,
``rationale`` = GEval's reason. The reference answer is optional: when present it's passed as the
expected output and the criteria can grade against it; when absent, GEval grades intrinsic
quality against the criteria alone.

GEval is conceptually close to our from-scratch ``LLMJudgeScorer`` — that's deliberate: this
adapter exists to prove the seam wraps a *second external framework* (alongside RAGAS) behind
one Protocol, the sprint's goal. Its internal LLM calls go through our gateway (see
:mod:`gateway_llm`), so no vendor SDK is touched directly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from promptforge_api.evals.scorer import Score
from promptforge_api.gateway import LLMGateway
from promptforge_worker.evals.gateway_llm import GatewayDeepEvalLLM

_logger = structlog.get_logger(__name__)

# GEval's own default gate; the score is in [0,1] like every other scorer.
_DEFAULT_PASS_THRESHOLD = 0.5

# A sensible default criteria when the run config doesn't supply one: graded correctness +
# relevance, the same substance the judge cares about, phrased for GEval's step generation.
_DEFAULT_CRITERIA = (
    "Determine whether the actual output is factually correct, directly answers the input, "
    "and is relevant. Penalise incorrect or irrelevant content; ignore length and style."
)


class DeepEvalGEvalScorer:
    """Grades an output against free-text criteria using DeepEval's GEval.

    Conforms structurally to :class:`promptforge_api.evals.scorer.Scorer`. The gateway is
    injected; GEval's internal LLM calls run through it via :class:`GatewayDeepEvalLLM`.
    """

    name = "deepeval_geval"

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        model: str = "openai/gpt-4o-mini",
        criteria: str = _DEFAULT_CRITERIA,
        pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
        metric_name: str = "Correctness",
    ) -> None:
        """Wire GEval to a gateway and its grading policy.

        ``criteria`` is the free-text grading instruction GEval expands into evaluation steps;
        ``metric_name`` is a human label recorded on the score. ``pass_threshold`` is our gate.
        """
        self._gateway = gateway
        self._model = model
        self._criteria = criteria
        self._pass_threshold = pass_threshold
        self._metric_name = metric_name

    async def score(
        self,
        *,
        input: str,
        output: str,
        reference: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Score:
        """Grade ``output`` against the criteria, returning GEval's score + reason as a Score."""
        # Only declare EXPECTED_OUTPUT as a grading input when we actually have a reference —
        # GEval validates that every declared param is present on the test case.
        eval_params: list[SingleTurnParams] = [
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ]
        if reference is not None:
            eval_params.append(SingleTurnParams.EXPECTED_OUTPUT)

        metric = GEval(
            name=self._metric_name,
            criteria=self._criteria,
            evaluation_params=eval_params,
            model=GatewayDeepEvalLLM(self._gateway, model=self._model),
            threshold=self._pass_threshold,
        )
        test_case = LLMTestCase(input=input, actual_output=output, expected_output=reference)

        _logger.info("deepeval_scoring_started", metric=self.name, model=self._model)
        await metric.a_measure(test_case)

        # GEval populates .score (0-1) and .reason after measuring. Default a missing score to 0
        # rather than crash the run; the reason is the model's written explanation.
        value = float(metric.score if metric.score is not None else 0.0)
        passed = value >= self._pass_threshold
        rationale = metric.reason or "(GEval returned no reason)"

        _logger.info("deepeval_scoring_finished", metric=self.name, value=value, passed=passed)
        return Score(
            value=value,
            passed=passed,
            rationale=rationale,
            metadata={
                "scorer": self.name,
                "metric_model": self._model,
                "metric_name": self._metric_name,
                "pass_threshold": self._pass_threshold,
                "evaluation_params": [str(p) for p in self._param_names(eval_params)],
            },
        )

    @staticmethod
    def _param_names(params: Sequence[SingleTurnParams]) -> list[str]:
        """Readable names of the grading params, for the stored metadata."""
        return [getattr(p, "value", str(p)) for p in params]
