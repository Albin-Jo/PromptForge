"""The promotion gate's *decision rule* — pure policy, no I/O (Sprint 11 / Phase 8).

Given a candidate version's eval summary, the current production version's summary (if any),
and a :class:`PromotionPolicy`, :func:`decide` returns whether the candidate may be promoted
and, if not, exactly why. Two independent bars, per scorer:

- **Absolute floor** — the candidate's pass-rate must clear ``min_quality``. This is "is it good
  enough at all?", and it applies even on a first promotion with no incumbent to compare against.
- **Regression** — the candidate's pass-rate must not fall more than ``max_quality_drop`` below
  the current production version's. This is "did this change make it *worse*?". It only runs when
  there's a production baseline **and** the golden set is at least ``min_dataset_size`` (below
  that, a one-item flip is a huge percentage swing — pure noise, not a regression; ADR 0016).

The function is **pure** (summaries + policy in, decision out), so it's tested exhaustively by
handing it fabricated summaries — the "evaluate the evaluator" discipline, same as
:mod:`promptforge_api.services.alerts`. The orchestration that loads the summaries, writes the
audit, and fires the webhook lives in :mod:`promptforge_api.services.promotion`.

Gating metric: **pass-rate** per scorer (the fraction of the golden set a scorer passed). A
``None`` pass-rate means the scorer produced no usable verdict (everything errored) — treated as
failing the floor, because a version we couldn't grade must not ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from promptforge_api.config import Settings


@dataclass(frozen=True)
class ScorerSummary:
    """One scorer's aggregate over a run — the slice of ``EvalRun.summary`` the gate reads."""

    name: str
    count: int
    passed: int
    pass_rate: float | None  # None when nothing was scored (all items errored)
    mean_value: float | None


@dataclass(frozen=True)
class RunSummary:
    """A completed eval run's aggregate, parsed from ``EvalRun.summary`` into typed form."""

    items: int
    scored: int
    errors: int
    scorers: dict[str, ScorerSummary] = field(default_factory=dict)

    @classmethod
    def from_eval_summary(cls, summary: dict[str, Any]) -> RunSummary:
        """Parse the JSON summary the eval runner writes (see ``EvalRunner._aggregate``)."""
        scorers: dict[str, ScorerSummary] = {}
        for name, block in (summary.get("scorers") or {}).items():
            scorers[name] = ScorerSummary(
                name=name,
                count=int(block.get("count", 0)),
                passed=int(block.get("passed", 0)),
                pass_rate=block.get("pass_rate"),
                mean_value=block.get("mean_value"),
            )
        return cls(
            items=int(summary.get("items", 0)),
            scored=int(summary.get("scored", 0)),
            errors=int(summary.get("errors", 0)),
            scorers=scorers,
        )


@dataclass(frozen=True)
class PromotionPolicy:
    """The bars a candidate is judged against (built from :class:`Settings`)."""

    gated_label: str
    min_quality: float
    max_quality_drop: float
    min_dataset_size: int

    @classmethod
    def from_settings(cls, settings: Settings) -> PromotionPolicy:
        return cls(
            gated_label=settings.promotion_gated_label,
            min_quality=settings.promotion_min_quality,
            max_quality_drop=settings.promotion_max_quality_drop,
            min_dataset_size=settings.promotion_min_dataset_size,
        )


@dataclass(frozen=True)
class MetricDelta:
    """The candidate-vs-production comparison for one scorer (the gate's evidence)."""

    scorer: str
    candidate: float | None
    baseline: float | None  # production's pass-rate, or None (no incumbent / scorer absent)
    drop: float | None  # baseline - candidate, when both are known
    floor_ok: bool
    regression: bool


@dataclass(frozen=True)
class PromotionDecision:
    """The verdict: allow or block, the human reasons, and the per-scorer evidence."""

    allowed: bool
    reasons: list[str]
    deltas: list[MetricDelta]
    regression_checked: bool

    def as_detail(self) -> dict[str, Any]:
        """Machine-readable evidence for the audit row + webhook payload."""
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "regression_checked": self.regression_checked,
            "deltas": [
                {
                    "scorer": d.scorer,
                    "candidate": d.candidate,
                    "baseline": d.baseline,
                    "drop": d.drop,
                    "floor_ok": d.floor_ok,
                    "regression": d.regression,
                }
                for d in self.deltas
            ],
        }


def decide(
    candidate: RunSummary, production: RunSummary | None, policy: PromotionPolicy
) -> PromotionDecision:
    """Decide whether *candidate* may be promoted over *production* under *policy*."""
    # The regression check is only trustworthy with a baseline and a large-enough golden set.
    regression_checked = production is not None and candidate.items >= policy.min_dataset_size

    deltas: list[MetricDelta] = []
    reasons: list[str] = []

    if not candidate.scorers:
        # Nothing was graded at all — can't establish quality, so it can't ship.
        reasons.append("candidate has no evaluation scores to judge")

    for name in sorted(candidate.scorers):
        cand_rate = candidate.scorers[name].pass_rate
        base = production.scorers.get(name) if production is not None else None
        base_rate = base.pass_rate if base is not None else None
        drop = base_rate - cand_rate if (base_rate is not None and cand_rate is not None) else None

        floor_ok = cand_rate is not None and cand_rate >= policy.min_quality
        regression = bool(
            regression_checked and drop is not None and drop > policy.max_quality_drop
        )

        deltas.append(
            MetricDelta(
                scorer=name,
                candidate=cand_rate,
                baseline=base_rate,
                drop=drop,
                floor_ok=floor_ok,
                regression=regression,
            )
        )

        if not floor_ok:
            if cand_rate is None:
                reasons.append(
                    f"scorer '{name}' produced no usable scores (nothing gradable to promote)"
                )
            else:
                reasons.append(
                    f"scorer '{name}' pass-rate {cand_rate:.2f} is below the floor "
                    f"{policy.min_quality:.2f}"
                )
        if regression:
            # drop / base_rate / cand_rate are all non-None here (regression implies it).
            assert drop is not None and base_rate is not None and cand_rate is not None
            reasons.append(
                f"scorer '{name}' regressed: pass-rate {cand_rate:.2f} is {drop:.2f} below "
                f"production's {base_rate:.2f} (max allowed drop {policy.max_quality_drop:.2f})"
            )

    return PromotionDecision(
        allowed=not reasons,
        reasons=reasons,
        deltas=deltas,
        regression_checked=regression_checked,
    )
