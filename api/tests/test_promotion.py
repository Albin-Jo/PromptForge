"""Unit tests for the pure promotion decision rule (``promotion.decide``).

The gate's verdict is pure (summaries + policy in, decision out), so it's exercised
exhaustively here with fabricated summaries — the "evaluate the evaluator" discipline,
no database or worker involved. The orchestration (loading runs, audit, webhook) is
covered by the integration tests in ``test_promotion_gate.py``.
"""

from __future__ import annotations

from promptforge_api.config import Settings
from promptforge_api.promotion import (
    PromotionPolicy,
    RunSummary,
    ScorerSummary,
    decide,
)

_POLICY = PromotionPolicy(
    gated_label="production", min_quality=0.7, max_quality_drop=0.05, min_dataset_size=5
)


def _summary(pass_rate: float | None, *, items: int = 10, scorer: str = "llm_judge") -> RunSummary:
    """A one-scorer run summary with the given pass-rate over *items* cases."""
    passed = 0 if pass_rate is None else round(pass_rate * items)
    return RunSummary(
        items=items,
        scored=items,
        errors=0,
        scorers={
            scorer: ScorerSummary(
                name=scorer, count=items, passed=passed, pass_rate=pass_rate, mean_value=pass_rate
            )
        },
    )


def test_clears_floor_no_baseline_is_allowed() -> None:
    decision = decide(_summary(0.9), None, _POLICY)
    assert decision.allowed
    assert decision.reasons == []
    assert decision.regression_checked is False  # no production baseline to compare against


def test_below_floor_is_blocked() -> None:
    decision = decide(_summary(0.6), None, _POLICY)
    assert not decision.allowed
    assert any("below the floor" in r for r in decision.reasons)
    assert decision.deltas[0].floor_ok is False


def test_regression_against_production_is_blocked() -> None:
    # Candidate clears the floor (0.8 >= 0.7) but drops 0.1 below production (0.9) > max_drop 0.05.
    decision = decide(_summary(0.8), _summary(0.9), _POLICY)
    assert not decision.allowed
    assert decision.regression_checked is True
    assert any("regressed" in r for r in decision.reasons)
    delta = decision.deltas[0]
    assert delta.regression is True
    assert delta.floor_ok is True
    assert delta.drop is not None and round(delta.drop, 2) == 0.1


def test_small_drop_within_tolerance_is_allowed() -> None:
    # A 0.04 drop is within max_quality_drop (0.05) — noise, not a regression.
    decision = decide(_summary(0.86), _summary(0.90), _POLICY)
    assert decision.allowed
    assert decision.deltas[0].regression is False


def test_regression_check_skipped_for_small_dataset() -> None:
    # Below min_dataset_size (5): the (noisy) regression check is skipped, floor still applies.
    candidate = _summary(0.8, items=3)  # clears floor
    production = _summary(1.0, items=3)  # would be a 0.2 "drop", but too few items to trust
    decision = decide(candidate, production, _POLICY)
    assert decision.allowed
    assert decision.regression_checked is False
    assert decision.deltas[0].regression is False


def test_unscorable_candidate_is_blocked() -> None:
    # pass_rate None = nothing graded (all items errored) — can't establish quality, so refuse.
    decision = decide(_summary(None), _summary(0.9), _POLICY)
    assert not decision.allowed
    assert any("no usable scores" in r for r in decision.reasons)


def test_no_scorers_is_blocked() -> None:
    empty = RunSummary(items=10, scored=0, errors=10, scorers={})
    decision = decide(empty, None, _POLICY)
    assert not decision.allowed
    assert any("no evaluation scores" in r for r in decision.reasons)


def test_production_missing_a_scorer_skips_its_regression() -> None:
    # Candidate has a scorer production never ran — no baseline for it, so floor-only (and it
    # clears the floor), no spurious regression.
    candidate = _summary(0.8, scorer="ragas_factual_correctness")
    production = _summary(0.9, scorer="llm_judge")
    decision = decide(candidate, production, _POLICY)
    assert decision.allowed
    assert decision.deltas[0].baseline is None
    assert decision.deltas[0].regression is False


def test_one_failing_scorer_blocks_the_lot() -> None:
    candidate = RunSummary(
        items=10,
        scored=20,
        errors=0,
        scorers={
            "llm_judge": ScorerSummary("llm_judge", 10, 9, 0.9, 0.9),
            "ragas_factual_correctness": ScorerSummary(
                "ragas_factual_correctness", 10, 5, 0.5, 0.5
            ),
        },
    )
    decision = decide(candidate, None, _POLICY)
    assert not decision.allowed
    assert any("ragas_factual_correctness" in r for r in decision.reasons)
    assert not any("'llm_judge'" in r for r in decision.reasons)  # the good scorer isn't flagged


def test_from_eval_summary_parses_runner_output() -> None:
    raw = {
        "items": 4,
        "scored": 4,
        "errors": 0,
        "error_details": [],
        "scorers": {"llm_judge": {"count": 4, "passed": 3, "pass_rate": 0.75, "mean_value": 0.8}},
    }
    summary = RunSummary.from_eval_summary(raw)
    assert summary.items == 4
    assert summary.scorers["llm_judge"].pass_rate == 0.75
    assert summary.scorers["llm_judge"].passed == 3


def test_policy_from_settings() -> None:
    policy = PromotionPolicy.from_settings(Settings())
    assert policy.gated_label == "production"
    assert policy.min_quality == 0.7
    assert policy.max_quality_drop == 0.05
    assert policy.min_dataset_size == 5


def test_decision_as_detail_round_trips_evidence() -> None:
    detail = decide(_summary(0.8), _summary(0.9), _POLICY).as_detail()
    assert detail["allowed"] is False
    assert detail["regression_checked"] is True
    assert detail["deltas"][0]["scorer"] == "llm_judge"
    assert detail["deltas"][0]["regression"] is True
