"""The scorer registry: turn a run's *config* into live :class:`Scorer` instances.

An eval run stores **which scorers to use** as data — a JSON list of specs like::

    [
      {"scorer": "llm_judge",                 "params": {"model": "openai/gpt-4o-mini"}},
      {"scorer": "ragas_factual_correctness", "params": {"pass_threshold": 0.6}}
    ]

— so "this run grades with the judge + a RAGAS metric" (the Sprint 8 DoD) is a configuration
choice, not a code change. The registry maps each spec's ``scorer`` name to a builder that
constructs the scorer with the shared gateway plus the spec's ``params``. The engine then drives
every resulting scorer through the one ``Scorer`` Protocol, never branching on which it holds.

This lives in the **worker** because only the worker runs evals and only it has ``ragas`` /
``deepeval`` installed (ADR 0011). The API stores and validates the *names*, but the API image
can't (and shouldn't) instantiate the framework-backed scorers. The judge, needing only the
gateway, is composed here from the API package alongside the two adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from promptforge_api.evals.llm_judge import LLMJudgeScorer
from promptforge_api.evals.scorer import Scorer
from promptforge_api.gateway import LLMGateway
from promptforge_worker.evals.deepeval_scorer import DeepEvalGEvalScorer
from promptforge_worker.evals.ragas_scorer import RagasFactualCorrectnessScorer

# A builder takes the shared gateway + this scorer's params and returns a ready scorer. Each
# scorer's constructor already validates/defaults its own params, so builders stay one-liners.
ScorerBuilder = Callable[[LLMGateway, Mapping[str, Any]], Scorer]


class UnknownScorerError(ValueError):
    """A run config named a scorer that isn't registered — fail fast, don't silently skip it."""


# The registry. Adding a new scorer is one line here + its module — the engine and the run
# wiring never change. Keys are the stable names stored in eval run configs (and in each
# Score's metadata), so renaming one is a data migration, not just a code edit.
_REGISTRY: dict[str, ScorerBuilder] = {
    LLMJudgeScorer.name: lambda gw, p: LLMJudgeScorer(gw, **_kwargs(p)),
    RagasFactualCorrectnessScorer.name: lambda gw, p: RagasFactualCorrectnessScorer(
        gw, **_kwargs(p)
    ),
    DeepEvalGEvalScorer.name: lambda gw, p: DeepEvalGEvalScorer(gw, **_kwargs(p)),
}


def _kwargs(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalise an optional params mapping to keyword args for a scorer constructor."""
    return dict(params) if params else {}


def available_scorers() -> tuple[str, ...]:
    """The registered scorer names — for config validation at the API boundary."""
    return tuple(_REGISTRY)


def build_scorer(spec: Mapping[str, Any], gateway: LLMGateway) -> Scorer:
    """Construct one scorer from a ``{"scorer": name, "params": {...}}`` spec.

    Raises :class:`UnknownScorerError` if ``scorer`` isn't registered, and ``KeyError`` if the
    spec has no ``scorer`` key at all — both are config bugs we want loud, not swallowed.
    """
    name = spec["scorer"]
    builder = _REGISTRY.get(name)
    if builder is None:
        raise UnknownScorerError(
            f"unknown scorer {name!r}; registered: {', '.join(available_scorers())}"
        )
    return builder(gateway, spec.get("params") or {})


def build_scorers(specs: Sequence[Mapping[str, Any]], gateway: LLMGateway) -> list[Scorer]:
    """Construct every scorer for a run, in config order. Empty config is a bug — reject it."""
    if not specs:
        raise UnknownScorerError("eval run has no scorers configured")
    return [build_scorer(spec, gateway) for spec in specs]
