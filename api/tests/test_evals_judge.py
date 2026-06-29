"""Evaluate the evaluator — tests for the LLM judge.

Most of these are **plumbing tests**: they inject a fake gateway backend returning a
*canned* judge reply and assert on the parts we own — that we (a) send a correctly
built, deterministic request and (b) parse the reply into the right :class:`Score`
(rubric→[0,1] mapping, pass gate, and every way a drifting reply is rejected). They do
*not* prove the judge *prompt* actually grades real outputs correctly — you can't,
without a live model.

That second, harder half of "evaluate the evaluator" — does the real judge score a
known-good answer as passing and a known-wrong one as failing? — is
``test_real_judge_grades_known_pairs`` at the bottom, gated on ``OPENAI_API_KEY`` so it
runs only when a key is present (and skips in CI). It's the regression guard for the
judge prompt itself.
"""

import json
import os
from typing import Any

import pytest
from fakes import openai_shaped_response, recording_backend

from promptforge_api.evals import JudgeParseError, LLMJudgeScorer, Score, Scorer
from promptforge_api.gateway import LLMGateway


def _judge_reply(rating: Any, rationale: str = "Looks correct and on-topic.") -> str:
    """A well-formed judge reply: rationale first, then rating (the JSON contract)."""
    return json.dumps({"rationale": rationale, "rating": rating})


def _gateway_returning(content: str) -> tuple[LLMGateway, dict[str, Any]]:
    """A real gateway wired to a fake backend that returns *content* and records kwargs.

    Using the real :class:`LLMGateway` (not a mock of it) means these tests also
    exercise our own response parsing — the judge depends on the true seam.
    """
    backend, captured = recording_backend(openai_shaped_response(content))
    return LLMGateway(completion_fn=backend), captured


def _judge(content: str) -> tuple[LLMJudgeScorer, dict[str, Any]]:
    gateway, captured = _gateway_returning(content)
    return LLMJudgeScorer(gateway), captured


# --- the DoD's known-correct pairs ------------------------------------------------


async def test_good_answer_scores_high_and_passes() -> None:
    judge, _ = _judge(_judge_reply(5, "Correct and complete."))

    score = await judge.score(
        input="What is the capital of France?",
        output="Paris.",
        reference="Paris",
    )

    assert isinstance(score, Score)
    assert score.value == 1.0  # rating 5 → (5-1)/(5-1)
    assert score.passed is True
    assert score.rationale == "Correct and complete."
    assert score.metadata["rating"] == 5


async def test_wrong_answer_scores_low_and_fails() -> None:
    judge, _ = _judge(_judge_reply(1, "Factually wrong."))

    score = await judge.score(
        input="What is the capital of France?",
        output="Berlin.",
        reference="Paris",
    )

    assert score.value == 0.0
    assert score.passed is False
    assert score.metadata["rating"] == 1


# --- rubric → [0,1] mapping and the pass gate -------------------------------------


@pytest.mark.parametrize(
    ("rating", "expected_value"),
    [(1, 0.0), (2, 0.25), (3, 0.5), (4, 0.75), (5, 1.0)],
)
async def test_rating_maps_linearly_to_unit_value(rating: int, expected_value: float) -> None:
    judge, _ = _judge(_judge_reply(rating))
    score = await judge.score(input="q", output="a")
    assert score.value == expected_value


async def test_pass_gate_is_ours_not_the_models() -> None:
    # Rating 3 → 0.5, below the default 0.7 gate → fail, even though "3" isn't awful.
    judge, _ = _judge(_judge_reply(3))
    assert (await judge.score(input="q", output="a")).passed is False
    # Rating 4 → 0.75 ≥ 0.7 → pass.
    judge4, _ = _judge(_judge_reply(4))
    assert (await judge4.score(input="q", output="a")).passed is True


async def test_threshold_is_configurable() -> None:
    gateway, _ = _gateway_returning(_judge_reply(5))
    strict = LLMJudgeScorer(gateway, pass_threshold=1.01)  # nothing can pass
    assert (await strict.score(input="q", output="a")).passed is False


# --- the request we build is deterministic and well-formed ------------------------


async def test_judge_request_is_deterministic() -> None:
    judge, captured = _judge(_judge_reply(4))
    await judge.score(input="q", output="a")
    # Temperature 0 + seed: the same output should grade the same way.
    assert captured["temperature"] == 0.0
    assert captured["seed"] == 7


async def test_reference_is_included_only_when_supplied() -> None:
    judge, captured = _judge(_judge_reply(4))
    await judge.score(input="q", output="a", reference="the gold answer")
    user_msg = captured["messages"][-1]["content"]
    assert "the gold answer" in user_msg

    judge2, captured2 = _judge(_judge_reply(4))
    await judge2.score(input="q", output="a")
    assert "REFERENCE ANSWER" not in captured2["messages"][-1]["content"]


async def test_reference_instructs_the_judge_how_to_use_it() -> None:
    # A reference in the user message is useless if the rubric never says to grade
    # against it; the system prompt must pick up a reference instruction (and not
    # invent one when there's no reference).
    judge, captured = _judge(_judge_reply(4))
    await judge.score(input="q", output="a", reference="Paris")
    system_with_ref = captured["messages"][0]["content"]
    assert "reference answer is provided" in system_with_ref.lower()

    judge2, captured2 = _judge(_judge_reply(4))
    await judge2.score(input="q", output="a")
    assert "reference answer is provided" not in captured2["messages"][0]["content"].lower()


async def test_criteria_from_context_reaches_the_system_prompt() -> None:
    judge, captured = _judge(_judge_reply(4))
    await judge.score(input="q", output="a", context={"criteria": "must cite a source"})
    system_msg = captured["messages"][0]["content"]
    assert "must cite a source" in system_msg


# --- a drifting judge reply is rejected, not silently averaged in -----------------


async def test_json_wrapped_in_markdown_fences_is_rescued() -> None:
    fenced = f"```json\n{_judge_reply(5)}\n```"
    judge, _ = _judge(fenced)
    score = await judge.score(input="q", output="a")
    assert score.metadata["rating"] == 5


async def test_non_json_reply_raises_parse_error() -> None:
    judge, _ = _judge("I think it's pretty good honestly")
    with pytest.raises(JudgeParseError):
        await judge.score(input="q", output="a")


async def test_missing_rating_raises_parse_error() -> None:
    judge, _ = _judge(json.dumps({"rationale": "no number here"}))
    with pytest.raises(JudgeParseError):
        await judge.score(input="q", output="a")


@pytest.mark.parametrize("bad_rating", [0, 6, 99])
async def test_rating_out_of_range_raises(bad_rating: int) -> None:
    judge, _ = _judge(_judge_reply(bad_rating))
    with pytest.raises(JudgeParseError):
        await judge.score(input="q", output="a")


async def test_non_integer_rating_raises() -> None:
    judge, _ = _judge(_judge_reply("excellent"))
    with pytest.raises(JudgeParseError):
        await judge.score(input="q", output="a")


async def test_boolean_rating_is_rejected() -> None:
    # bool is an int subclass; "true" must not be read as rating 1.
    judge, _ = _judge(json.dumps({"rationale": "x", "rating": True}))
    with pytest.raises(JudgeParseError):
        await judge.score(input="q", output="a")


async def test_missing_rationale_keeps_the_rating() -> None:
    # The number without reasoning is degraded, not discarded.
    judge, _ = _judge(json.dumps({"rating": 5}))
    score = await judge.score(input="q", output="a")
    assert score.value == 1.0
    assert "no rationale" in score.rationale.lower()


async def test_rating_before_rationale_is_parsed_but_warned() -> None:
    # The model inverted the contracted key order (rating first), so its reasoning is
    # post-hoc. We still parse the verdict, but the anti-anchoring violation must be
    # observable rather than silent.
    from structlog.testing import capture_logs

    inverted = json.dumps({"rating": 5, "rationale": "decided after the number"})
    judge, _ = _judge(inverted)
    with capture_logs() as logs:
        score = await judge.score(input="q", output="a")

    assert score.value == 1.0  # verdict still usable
    assert any(entry["event"] == "judge_rationale_after_rating" for entry in logs)


def test_judge_conforms_to_scorer_protocol() -> None:
    gateway, _ = _gateway_returning(_judge_reply(5))
    judge: Scorer = LLMJudgeScorer(gateway)  # structural typing: assignment type-checks
    assert judge.name == "llm_judge"


# --- the hard half: does the real judge prompt actually grade correctly? -----------
# Gated on a real key; skipped in CI and on any machine without one. This is the
# regression guard for the judge *prompt* (not our parsing) — if a model or prompt
# change makes the judge pass a wrong answer, this is what catches it.


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="needs a real OPENAI_API_KEY; this exercises the live judge prompt",
)
async def test_real_judge_grades_known_pairs() -> None:
    judge = LLMJudgeScorer(LLMGateway())  # real litellm backend

    good = await judge.score(
        input="What is the capital of France?", output="Paris.", reference="Paris"
    )
    assert good.passed is True
    assert good.value >= 0.75

    bad = await judge.score(
        input="What is the capital of France?", output="Berlin.", reference="Paris"
    )
    assert bad.passed is False
    assert bad.value <= 0.5
