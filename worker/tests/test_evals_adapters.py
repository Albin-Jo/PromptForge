"""Unit tests for the worker's framework adapters + scorer registry (Sprint 8 chunk 2).

These verify the *seam*, not the frameworks themselves: that each adapter (a) structurally
satisfies the API's ``Scorer`` Protocol, (b) maps a framework verdict onto our :class:`Score`
correctly, and (c) is selectable by config through the registry. The frameworks' own LLM-driven
scoring is monkeypatched to a known verdict so these tests need no network or key — a real
ragas/deepeval run against a live model is exercised separately, key-gated, like the judge's.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from promptforge_api.evals.scorer import Score
from promptforge_api.gateway import LLMGateway
from promptforge_worker.evals.deepeval_scorer import DeepEvalGEvalScorer
from promptforge_worker.evals.gateway_llm import GatewayDeepEvalLLM, GatewayRagasLLM
from promptforge_worker.evals.ragas_scorer import (
    RagasFactualCorrectnessError,
    RagasFactualCorrectnessScorer,
)
from promptforge_worker.evals.registry import (
    UnknownScorerError,
    available_scorers,
    build_scorer,
    build_scorers,
)


def _gateway_returning(text: str) -> LLMGateway:
    """An LLMGateway wired to a fake backend that always returns *text* (no network)."""

    async def backend(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            model="openai/gpt-4o-mini",
            choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
            usage=None,
        )

    return LLMGateway(backend)


# --- The registry: select scorers by config -------------------------------------------------


def test_registry_builds_each_registered_scorer() -> None:
    gw = _gateway_returning("{}")
    judge = build_scorer({"scorer": "llm_judge"}, gw)
    ragas = build_scorer({"scorer": "ragas_factual_correctness"}, gw)
    geval = build_scorer({"scorer": "deepeval_geval"}, gw)
    assert judge.name == "llm_judge"
    assert ragas.name == "ragas_factual_correctness"
    assert geval.name == "deepeval_geval"


def test_registry_passes_params_to_constructor() -> None:
    gw = _gateway_returning("{}")
    scorer = build_scorer(
        {
            "scorer": "ragas_factual_correctness",
            "params": {"pass_threshold": 0.9, "mode": "recall"},
        },
        gw,
    )
    assert isinstance(scorer, RagasFactualCorrectnessScorer)
    assert scorer._pass_threshold == 0.9
    assert scorer._mode == "recall"


def test_registry_builds_a_full_multi_scorer_run() -> None:
    """The DoD config: 'judge + a RAGAS metric' resolves to two scorers, in order."""
    gw = _gateway_returning("{}")
    scorers = build_scorers([{"scorer": "llm_judge"}, {"scorer": "ragas_factual_correctness"}], gw)
    assert [s.name for s in scorers] == ["llm_judge", "ragas_factual_correctness"]


def test_registry_rejects_unknown_scorer() -> None:
    with pytest.raises(UnknownScorerError, match="unknown scorer 'nope'"):
        build_scorer({"scorer": "nope"}, _gateway_returning("{}"))


def test_registry_rejects_empty_config() -> None:
    with pytest.raises(UnknownScorerError, match="no scorers configured"):
        build_scorers([], _gateway_returning("{}"))


def test_available_scorers_lists_all_three() -> None:
    assert set(available_scorers()) == {
        "llm_judge",
        "ragas_factual_correctness",
        "deepeval_geval",
    }


# --- RAGAS adapter: Score mapping + reference requirement ------------------------------------


async def test_ragas_scorer_requires_a_reference() -> None:
    scorer = RagasFactualCorrectnessScorer(_gateway_returning("{}"))
    with pytest.raises(RagasFactualCorrectnessError, match="reference-based"):
        await scorer.score(input="q", output="a", reference=None)


async def test_ragas_scorer_maps_metric_score_to_a_passing_score(monkeypatch: Any) -> None:
    # Monkeypatch the RAGAS metric's async scoring to a known f1, so we test *our* mapping.
    from ragas.metrics import FactualCorrectness

    async def fake_single_turn_ascore(self: Any, sample: Any, *a: Any, **k: Any) -> float:
        return 0.8

    monkeypatch.setattr(FactualCorrectness, "single_turn_ascore", fake_single_turn_ascore)

    scorer = RagasFactualCorrectnessScorer(_gateway_returning("{}"), pass_threshold=0.5)
    score = await scorer.score(input="q", output="a", reference="ref")

    assert isinstance(score, Score)
    assert score.value == 0.8
    assert score.passed is True  # 0.8 >= 0.5
    assert "FactualCorrectness" in score.rationale
    assert score.metadata["scorer"] == "ragas_factual_correctness"
    assert score.metadata["rationale_synthetic"] is True


async def test_ragas_scorer_fails_below_threshold(monkeypatch: Any) -> None:
    from ragas.metrics import FactualCorrectness

    async def fake_score(self: Any, sample: Any, *a: Any, **k: Any) -> float:
        return 0.3

    monkeypatch.setattr(FactualCorrectness, "single_turn_ascore", fake_score)
    scorer = RagasFactualCorrectnessScorer(_gateway_returning("{}"), pass_threshold=0.5)
    score = await scorer.score(input="q", output="a", reference="ref")
    assert score.value == 0.3
    assert score.passed is False


# --- DeepEval adapter: Score mapping + param wiring ------------------------------------------


async def test_deepeval_scorer_maps_geval_to_score(monkeypatch: Any) -> None:
    from deepeval.metrics import GEval

    async def fake_a_measure(self: Any, test_case: Any, *a: Any, **k: Any) -> float:
        self.score = 0.9
        self.reason = "The output is correct and relevant."
        return self.score

    monkeypatch.setattr(GEval, "a_measure", fake_a_measure)

    scorer = DeepEvalGEvalScorer(_gateway_returning("{}"), pass_threshold=0.5)
    score = await scorer.score(input="q", output="a", reference="ref")

    assert score.value == 0.9
    assert score.passed is True
    assert score.rationale == "The output is correct and relevant."
    assert score.metadata["scorer"] == "deepeval_geval"
    # reference present → EXPECTED_OUTPUT is among the graded params
    assert any("expected_output" in p for p in score.metadata["evaluation_params"])


async def test_deepeval_scorer_omits_expected_output_without_reference(monkeypatch: Any) -> None:
    from deepeval.metrics import GEval

    async def fake_a_measure(self: Any, test_case: Any, *a: Any, **k: Any) -> float:
        self.score = 0.6
        self.reason = "ok"
        return self.score

    monkeypatch.setattr(GEval, "a_measure", fake_a_measure)
    scorer = DeepEvalGEvalScorer(_gateway_returning("{}"))
    score = await scorer.score(input="q", output="a", reference=None)
    assert not any("expected_output" in p for p in score.metadata["evaluation_params"])


# --- Gateway-backed LLM wrappers ------------------------------------------------------------


async def test_ragas_llm_wrapper_routes_through_gateway() -> None:
    from langchain_core.prompt_values import StringPromptValue

    llm = GatewayRagasLLM(_gateway_returning("decomposed claims"), model="openai/gpt-4o-mini")
    result = await llm.agenerate_text(StringPromptValue(text="decompose this"))
    assert result.generations[0][0].text == "decomposed claims"
    assert llm.is_finished(result) is True


async def test_deepeval_llm_wrapper_routes_through_gateway() -> None:
    llm = GatewayDeepEvalLLM(_gateway_returning("a verdict"), model="openai/gpt-4o-mini")
    assert await llm.a_generate("grade this") == "a verdict"
    assert llm.get_model_name() == "openai/gpt-4o-mini"


# --- the hard half: do the REAL frameworks actually drive our gateway wrappers? --------------
# The tests above stub each framework at its scoring boundary, so they prove our *mapping*, not
# that ragas/deepeval can run through GatewayRagasLLM / GatewayDeepEvalLLM end to end (incl. the
# sync-shim path). These do — against a real model — and so are gated on a real key and skipped in
# CI, exactly like the judge's `test_real_judge_grades_known_pairs`. Run them locally once with a
# key to confirm the adapters work for real; they are the regression guard if a framework upgrade
# changes how it calls our LLM wrapper.

_NEEDS_KEY = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="needs a real OPENAI_API_KEY; exercises the live framework through our gateway wrapper",
)


@_NEEDS_KEY
async def test_real_ragas_factual_correctness_grades_known_pairs() -> None:
    scorer = RagasFactualCorrectnessScorer(LLMGateway())  # real litellm backend

    good = await scorer.score(
        input="What is the capital of France?",
        output="The capital of France is Paris.",
        reference="Paris",
    )
    bad = await scorer.score(
        input="What is the capital of France?",
        output="The capital of France is Berlin.",
        reference="Paris",
    )
    # A factually-correct answer should out-score a wrong one (the metric's whole job).
    assert good.value > bad.value


@_NEEDS_KEY
async def test_real_deepeval_geval_grades_known_pairs() -> None:
    scorer = DeepEvalGEvalScorer(LLMGateway())  # real litellm backend

    good = await scorer.score(
        input="What is the capital of France?", output="Paris.", reference="Paris"
    )
    bad = await scorer.score(
        input="What is the capital of France?", output="Berlin.", reference="Paris"
    )
    assert good.passed is True
    assert good.value > bad.value
