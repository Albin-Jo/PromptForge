"""The evaluation engine: pluggable scorers that grade prompt outputs.

Everything outside this package depends on the :class:`~promptforge_api.evals.scorer.Scorer`
Protocol and the :class:`~promptforge_api.evals.scorer.Score` result, never on a
specific scorer. :class:`~promptforge_api.evals.llm_judge.LLMJudgeScorer` is the first
implementation (Sprint 7); exact-match/embedding scorers slot in behind the same
Protocol later.
"""

from promptforge_api.evals.errors import JudgeParseError, ScorerError
from promptforge_api.evals.llm_judge import LLMJudgeScorer
from promptforge_api.evals.scorer import Score, Scorer

__all__ = [
    "JudgeParseError",
    "LLMJudgeScorer",
    "Score",
    "Scorer",
    "ScorerError",
]
