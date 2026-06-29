"""The eval runner: generate outputs for a golden set, score them, persist the verdicts.

This is the heart of Sprint 8 — what the ``run_eval`` Celery task drives. Given an
:class:`EvalRun` (which names a prompt *version*, a *dataset*, and a *scorer config*), it:

1. **generates** — for each dataset item, renders the version with the item's input and calls
   the gateway to produce the model output under test (the "generate-then-score" decision);
2. **scores** — runs every configured scorer over each (input, output, reference) triple,
   driving them all through the one ``Scorer`` Protocol;
3. **persists** — writes one ``ScoreRecord`` per (item, scorer), tagged with the scorer name;
4. **aggregates** — computes a per-scorer ``summary`` (pass_rate / mean / counts) on the run.

It owns no transaction or status: the task passes a live session and manages the run lifecycle
(pending → running → completed | failed), so the whole run commits or rolls back as one unit.

**Error policy (Sprint 8 decision).** Known per-item problems — a reference-less item handed to
the reference-based RAGAS metric, or a judge that returns unparseable JSON — are *recorded* in
the summary and the run continues. A *retryable* gateway failure is re-raised as
:class:`TransientEvalError` so the task retries the whole run; a permanent gateway failure
propagates and fails the run. The summary is descriptive, not a promotion gate — gating on it is
Sprint 11's job.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import DatasetItem, EvalRun, ScoreRecord
from promptforge_api.db.models import PromptVersion
from promptforge_api.evals.errors import JudgeParseError
from promptforge_api.evals.scorer import Score, Scorer
from promptforge_api.gateway import LLMGateway, Message, ModelConfig
from promptforge_api.gateway.errors import RETRYABLE_ERRORS, GatewayError
from promptforge_api.templating import render_template
from promptforge_worker.errors import TransientEvalError
from promptforge_worker.evals.ragas_scorer import RagasFactualCorrectnessError
from promptforge_worker.evals.registry import build_scorers

_logger = structlog.get_logger(__name__)

# Default model for *generating* the output under test, when the version's model_settings don't
# name one. Distinct from each scorer's own judge model (those are set in the scorer config).
_DEFAULT_GENERATION_MODEL = "openai/gpt-4o-mini"

# Per-item problems we treat as "record and continue" rather than fail the run. Both are
# structural (a missing reference, a malformed judge reply), not transient infrastructure faults.
_RECOVERABLE_SCORE_ERRORS = (RagasFactualCorrectnessError, JudgeParseError)


class EvalConfigError(ValueError):
    """The run is unrunnable as configured — no version, no dataset, or an empty dataset."""


class EvalInputMappingError(ValueError):
    """A dataset item's input can't be mapped onto the version's template (see _build_messages)."""


class EvalRunner:
    """Generates and scores a golden set for one :class:`EvalRun`, writing per-item verdicts."""

    def __init__(
        self, gateway: LLMGateway, *, default_generation_model: str = _DEFAULT_GENERATION_MODEL
    ) -> None:
        self._gateway = gateway
        self._default_model = default_generation_model

    async def run(self, session: Session, run: EvalRun) -> dict[str, Any]:
        """Execute *run* against its dataset, persist scores, set + return ``run.summary``.

        The caller owns the transaction and the status lifecycle; this method only reads the
        run's config, writes ``ScoreRecord`` rows into *session*, and assigns ``run.summary``.
        """
        version, items, scorers = self._load(session, run)

        scores_by_scorer: dict[str, list[Score]] = {s.name: [] for s in scorers}
        errors: list[dict[str, Any]] = []

        for item in items:
            try:
                output = await self._generate(version, item.input)
            except EvalInputMappingError as exc:
                # Can't produce an output for this item — it's unscorable; record and move on.
                errors.append({"item_id": str(item.id), "stage": "generate", "error": str(exc)})
                continue

            for scorer in scorers:
                score = await self._score_one(scorer, item=item, output=output, errors=errors)
                if score is not None:
                    session.add(_to_record(run.id, scorer.name, item.id, score))
                    scores_by_scorer[scorer.name].append(score)

        run.summary = self._aggregate(scores_by_scorer, item_count=len(items), errors=errors)
        _logger.info(
            "eval_run_aggregated",
            eval_run_id=str(run.id),
            items=len(items),
            errors=len(errors),
            scorers=list(scores_by_scorer),
        )
        return run.summary

    # --- loading -----------------------------------------------------------------------------

    def _load(
        self, session: Session, run: EvalRun
    ) -> tuple[PromptVersion, list[DatasetItem], list[Scorer]]:
        """Resolve the run's version, dataset items, and scorers, or fail with config errors."""
        if run.prompt_version_id is None:
            raise EvalConfigError("eval run has no prompt_version_id to generate from")
        version = session.get(PromptVersion, run.prompt_version_id)
        if version is None:
            raise EvalConfigError(f"prompt version {run.prompt_version_id} not found")

        if run.dataset_id is None:
            raise EvalConfigError("eval run has no dataset_id to evaluate against")
        items = list(
            session.scalars(
                select(DatasetItem)
                .where(DatasetItem.dataset_id == run.dataset_id)
                .order_by(DatasetItem.created_at)
            )
        )
        if not items:
            raise EvalConfigError(f"dataset {run.dataset_id} has no items")

        scorers = build_scorers(run.scorer_config, self._gateway)
        return version, items, scorers

    # --- generation --------------------------------------------------------------------------

    async def _generate(self, version: PromptVersion, item_input: str) -> str:
        """Render the version for this item's input and call the model to produce the output."""
        messages = self._build_messages(version, item_input)
        model = (version.model_settings or {}).get("model") or self._default_model
        try:
            completion = await self._gateway.complete(
                config=ModelConfig(model=model), messages=messages
            )
        except GatewayError as exc:
            raise _classify_gateway_error(exc) from exc
        return completion.content

    def _build_messages(self, version: PromptVersion, item_input: str) -> list[Message]:
        """Map ``item_input`` onto the version's template (Sprint 8 'smart mapping' decision).

        - If the input parses as a JSON **object**, treat it as the ``{{var}}`` map and render.
        - Else (plain text): fill the *sole* declared variable with it; or, if the version
          declares *no* variables, send the content as a system message and the input as the
          user turn. A plain-text input can't fill a multi-variable template — that's an error.
        """
        declared = list(version.input_variables or [])
        parsed = _try_json_object(item_input)

        if parsed is not None:
            variables = {key: str(value) for key, value in parsed.items()}
            missing = set(declared) - set(variables)
            if missing:
                raise EvalInputMappingError(
                    f"item JSON is missing declared template variables: {sorted(missing)}"
                )
            return [Message(role="user", content=render_template(version.content, variables))]

        if len(declared) == 1:
            rendered = render_template(version.content, {declared[0]: item_input})
            return [Message(role="user", content=rendered)]
        if not declared:
            return [
                Message(role="system", content=version.content),
                Message(role="user", content=item_input),
            ]
        raise EvalInputMappingError(
            f"plain-text input can't fill {len(declared)} template variables {declared}; "
            "store the item input as a JSON object of variables"
        )

    # --- scoring -----------------------------------------------------------------------------

    async def _score_one(
        self, scorer: Scorer, *, item: DatasetItem, output: str, errors: list[dict[str, Any]]
    ) -> Score | None:
        """Score one item with one scorer; record recoverable failures, re-raise the rest."""
        try:
            return await scorer.score(
                input=item.input,
                output=output,
                reference=item.reference,
                context=item.item_metadata,
            )
        except _RECOVERABLE_SCORE_ERRORS as exc:
            errors.append({"item_id": str(item.id), "scorer": scorer.name, "error": str(exc)})
            return None
        except GatewayError as exc:
            raise _classify_gateway_error(exc) from exc

    # --- aggregation -------------------------------------------------------------------------

    @staticmethod
    def _aggregate(
        scores_by_scorer: Mapping[str, Sequence[Score]],
        *,
        item_count: int,
        errors: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Build the run summary: per-scorer pass_rate / mean / counts, plus item + error totals."""
        per_scorer: dict[str, Any] = {}
        for name, scores in scores_by_scorer.items():
            n = len(scores)
            passed = sum(1 for s in scores if s.passed)
            per_scorer[name] = {
                "count": n,
                "passed": passed,
                # None (not 0) when nothing scored, so "no data" differs from "all failed".
                "pass_rate": (passed / n if n else None),
                "mean_value": (sum(s.value for s in scores) / n if n else None),
            }
        return {
            "items": item_count,
            "scored": sum(len(s) for s in scores_by_scorer.values()),
            "errors": len(errors),
            "error_details": list(errors),
            "scorers": per_scorer,
        }


def _to_record(run_id: Any, scorer_name: str, item_id: Any, score: Score) -> ScoreRecord:
    """Turn an in-memory :class:`Score` into its durable ``ScoreRecord`` row."""
    return ScoreRecord(
        eval_run_id=run_id,
        scorer_name=scorer_name,
        dataset_item_id=item_id,
        value=score.value,
        passed=score.passed,
        rationale=score.rationale,
        score_metadata=dict(score.metadata),
    )


def _try_json_object(text: str) -> dict[str, Any] | None:
    """Parse *text* as a JSON object, or return ``None`` if it isn't one (plain text / a list)."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _classify_gateway_error(exc: GatewayError) -> Exception:
    """Map a gateway failure to retry-the-run (transient) or fail-the-run (permanent).

    The gateway already retried *retryable* errors internally and exhausted them; re-raising as
    :class:`TransientEvalError` gives the whole run another attempt under the task's longer
    backoff (the provider may recover). Permanent errors (auth, bad request) won't improve on a
    retry, so they propagate and fail the run.
    """
    if isinstance(exc, RETRYABLE_ERRORS):
        return TransientEvalError(f"retryable gateway failure during eval: {exc}")
    return exc


class EvalRunNotFoundError(LookupError):
    """The run id handed to the task doesn't exist — a permanent failure, not worth retrying."""
