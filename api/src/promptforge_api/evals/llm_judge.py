"""An LLM-as-judge scorer, built from scratch on top of the gateway.

The idea: ask a capable model to *grade* another model's output and explain itself,
turning the open question "is this answer good?" into a structured :class:`Score`.
It's cheap, flexible, and needs no reference answer — but an LLM judge is **biased**
(learning-backlog, Sprint 7), so the whole design here is about constraining it:

- **A rubric, not a vibe.** The judge rates on a fixed 1–5 scale with concrete
  anchors, instead of "give it a score" — far more stable across runs and outputs.
- **Rationale before score.** The JSON contract puts ``rationale`` *before*
  ``rating``, so the model commits to its reasoning first and the number follows
  from it (cheap chain-of-thought), rather than picking a number and rationalising.
- **Style-blind.** The prompt tells the judge to ignore length, tone, and
  formatting and grade only correctness/relevance — countering verbosity bias.
- **Determinism.** Temperature 0 and a fixed seed cut run-to-run variance, so the
  same output tends to get the same verdict (the variance the stats Learn item is
  about).
- **We own the gate.** The model returns a *rating*; ``passed`` is computed here
  from our ``pass_threshold``, not taken from the model — the promotion gate
  (Sprint 11) is our policy, not the judge's mood.

The rating maps linearly onto the :class:`Score`'s ``[0,1]`` ``value`` so judge
scores sit on the same scale as every other scorer.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

import structlog

from promptforge_api.evals.errors import JudgeParseError
from promptforge_api.evals.scorer import Score
from promptforge_api.gateway import LLMGateway, Message, ModelConfig

_logger = structlog.get_logger(__name__)

# The rubric's bounds. A 1–5 integer scale is the LLM-judge convention (MT-Bench):
# coarse enough that the model is consistent, fine enough to separate "perfect" from
# "mostly right". value = (rating - MIN) / (MAX - MIN) → 1→0.0, 3→0.5, 5→1.0.
_RATING_MIN = 1
_RATING_MAX = 5

# Default gate: rating 4 or 5 passes (value 0.75 / 1.0), rating ≤3 fails. A judge
# call that lands exactly on the boundary passes (``>=``). Tunable per scorer.
_DEFAULT_PASS_THRESHOLD = 0.7

# The judge's job description and the rubric. Two optional slots are filled by
# _build_messages: {criteria_clause} injects caller-supplied grading criteria, and
# {reference_clause} tells the judge how to use the gold answer when the user message
# carries one (the reference text itself lives in _USER_TEMPLATE, not here).
_SYSTEM_PROMPT = """\
You are a strict, impartial evaluator of AI assistant outputs. You grade one \
response and explain your reasoning.

Grade ONLY on substance: factual correctness, whether it answers what was asked, \
and relevance.{criteria_clause}{reference_clause} Explicitly IGNORE length, verbosity, \
tone, and formatting — a short correct answer must score higher than a long wrong one. \
Do not reward confidence; reward correctness. Do not assume the response is good by \
default.

Rate on this 1-5 scale:
- 5: Fully correct and complete; nothing important wrong or missing.
- 4: Correct, with only minor omissions or imprecision.
- 3: Partially correct; a notable error or a missing key point.
- 2: Mostly incorrect or largely misses the question.
- 1: Completely incorrect, irrelevant, or empty.

Respond with a single JSON object and nothing else, with these keys IN THIS ORDER:
  "rationale": a one-to-three sentence explanation of the grade, written BEFORE you
               decide the number.
  "rating": an integer from 1 to 5.
Do not wrap the JSON in markdown fences or add any text around it."""

_USER_TEMPLATE = """\
[QUESTION / INPUT]
{input}

[ASSISTANT OUTPUT TO GRADE]
{output}{reference_block}

Grade the assistant output now as a JSON object."""


class LLMJudgeScorer:
    """Grades an output by asking an LLM to rate it against a rubric.

    Conforms structurally to :class:`~promptforge_api.evals.scorer.Scorer`. The
    gateway is injected (ADR 0006): the judge depends on *our* provider seam, not on
    any vendor, and tests pass a fake gateway so the suite needs no network or key.
    """

    name = "llm_judge"

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        model: str = "openai/gpt-4o-mini",
        pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
        seed: int | None = 7,
    ) -> None:
        """Wire the judge to a gateway and its grading policy.

        ``model`` is a LiteLLM provider-prefixed id — the judge model can differ
        from the model being graded (and usually should: don't let a model grade its
        own family — self-preference bias). ``pass_threshold`` is the ``[0,1]`` gate
        for ``passed``. ``seed`` (with temperature 0) makes the verdict as repeatable
        as the provider allows.
        """
        self._gateway = gateway
        self._model = model
        self._pass_threshold = pass_threshold
        self._seed = seed

    async def score(
        self,
        *,
        input: str,
        output: str,
        reference: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Score:
        """Ask the judge to rate ``output``, then turn its reply into a :class:`Score`.

        Raises :class:`~promptforge_api.evals.errors.JudgeParseError` if the model's
        reply can't be read as a rubric verdict; provider failures surface as the
        gateway's own ``GatewayError`` (we don't disguise an outage as a bad grade).
        """
        criteria = self._extract_criteria(context)
        messages = self._build_messages(
            input=input, output=output, reference=reference, criteria=criteria
        )
        # Temperature 0 + seed: we want the *same* output to grade the same way.
        config = ModelConfig(model=self._model, temperature=0.0, seed=self._seed)

        _logger.info(
            "judge_scoring_started",
            judge_model=self._model,
            has_reference=reference is not None,
        )
        completion = await self._gateway.complete(config=config, messages=messages)

        rating, rationale = _parse_verdict(completion.content)
        value = (rating - _RATING_MIN) / (_RATING_MAX - _RATING_MIN)
        passed = value >= self._pass_threshold

        _logger.info(
            "judge_scoring_finished",
            judge_model=self._model,
            rating=rating,
            value=value,
            passed=passed,
        )
        return Score(
            value=value,
            passed=passed,
            rationale=rationale,
            metadata={
                "scorer": self.name,
                "judge_model": self._model,
                "rating": rating,
                "rating_scale": f"{_RATING_MIN}-{_RATING_MAX}",
                "pass_threshold": self._pass_threshold,
                "provider_model": completion.model,
            },
        )

    @staticmethod
    def _extract_criteria(context: Mapping[str, Any] | None) -> str | None:
        """Pull an optional free-text ``criteria`` string out of ``context``."""
        if not context:
            return None
        criteria = context.get("criteria")
        return criteria if isinstance(criteria, str) and criteria.strip() else None

    def _build_messages(
        self, *, input: str, output: str, reference: str | None, criteria: str | None
    ) -> list[Message]:
        """Assemble the system rubric + the user grading request."""
        criteria_clause = f" Apply these specific criteria: {criteria}." if criteria else ""

        # A reference answer turns this into reference-based grading; the system prompt
        # must say *how* to use it (semantic match, not verbatim), or the judge is left
        # to guess. Without one, the judge grades intrinsic quality against the rubric.
        reference_clause = (
            " A reference answer is provided below; grade the output's correctness"
            " against it, accepting semantically equivalent answers — do not require"
            " identical wording."
            if reference is not None
            else ""
        )
        system = _SYSTEM_PROMPT.format(
            criteria_clause=criteria_clause, reference_clause=reference_clause
        )

        reference_block = (
            f"\n\n[REFERENCE ANSWER (the expected correct answer)]\n{reference}"
            if reference is not None
            else ""
        )
        user = _USER_TEMPLATE.format(input=input, output=output, reference_block=reference_block)
        return [Message(role="system", content=system), Message(role="user", content=user)]


# A JSON object embedded anywhere in the reply, as a last-resort rescue when a model
# ignores "no markdown fences" and wraps the object in prose or ```json fences. Greedy
# (first ``{`` to last ``}``) on purpose: it spans a nested object correctly, where a
# non-greedy ``.*?`` would stop at the first inner ``}``. Only reached when the whole
# reply isn't already valid JSON.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verdict(content: str) -> tuple[int, str]:
    """Read the judge's reply into a ``(rating, rationale)`` pair, defensively.

    The judge is *asked* for bare JSON, but models drift, so we (1) try the whole
    reply as JSON, (2) fall back to the first ``{...}`` span if it's wrapped in
    prose/fences, then validate the rating is an int in range. Anything we can't
    read becomes a :class:`JudgeParseError` carrying the raw text — a drifting judge
    is a signal to see, not to silently average into a pass rate.
    """
    payload = _load_json_object(content)
    if payload is None:
        raise JudgeParseError("judge did not return a JSON object", raw_output=content)

    if "rating" not in payload:
        raise JudgeParseError("judge JSON missing 'rating'", raw_output=content)
    rating = _coerce_rating(payload["rating"], raw=content)

    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        # The number without the reasoning defeats the point of a judge; still, don't
        # discard a valid rating — record the gap rather than failing the whole score.
        rationale = "(judge returned no rationale)"

    # The rationale-before-rating contract is anti-anchoring, but JSON key *order* the
    # model can silently invert. json.loads preserves insertion order, so we can at
    # least detect it: rating emitted before rationale means the score came first and
    # the reasoning is post-hoc. Surface it (the verdict is still usable) rather than
    # let the mitigation fail invisibly.
    keys = list(payload.keys())
    if "rationale" in keys and keys.index("rating") < keys.index("rationale"):
        _logger.warning("judge_rationale_after_rating", raw_keys=keys)

    return rating, rationale.strip()


def _load_json_object(content: str) -> dict[str, Any] | None:
    """Parse ``content`` as a JSON object, rescuing an embedded ``{...}`` if needed."""
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_rating(raw_rating: Any, *, raw: str) -> int:
    """Validate the rating is an integer (or integral float/str) within the scale."""
    if isinstance(raw_rating, bool):  # bool is an int subclass — reject it explicitly
        raise JudgeParseError("judge 'rating' was a boolean", raw_output=raw)
    try:
        rating = int(raw_rating)
    except (TypeError, ValueError):
        raise JudgeParseError(
            f"judge 'rating' was not an integer: {raw_rating!r}", raw_output=raw
        ) from None
    if not _RATING_MIN <= rating <= _RATING_MAX:
        raise JudgeParseError(
            f"judge 'rating' {rating} outside {_RATING_MIN}-{_RATING_MAX}", raw_output=raw
        )
    return rating
