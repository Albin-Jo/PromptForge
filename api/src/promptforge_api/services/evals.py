"""Evaluation use-cases exposed to the API: golden sets, eval triggering, status.

Sprint 7/8 built the eval *engine* (models + the worker runner) but no API surface to
drive it; this service is that surface, plus the bits the promotion gate (Sprint 11)
leans on. It:

- creates and reads **datasets** (golden sets) and attaches one to a prompt;
- **triggers** an eval for a version — creates a ``pending`` ``EvalRun`` and hands its id
  to ``submit_eval`` (the Celery enqueue), the eager half of "eval on version-create";
- reports a version's derived **eval status** (unevaluated / pending / running / completed
  / failed) without storing it on the immutable version row.

Speaks plain arguments and ORM entities, never Pydantic (ADR 0003). The enqueue is taken
by injection (a ``Callable[[UUID], None]``) so the service never imports Celery and tests
can pass a recorder — the same decoupling the SDK/gateway use for their backends.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func

from promptforge_api.db.eval_models import Dataset, DatasetItem, EvalRun
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.exceptions import (
    DatasetAlreadyExistsError,
    DatasetInUseError,
    DatasetNotFoundError,
    EmptyGoldenSetError,
    GoldenSetMissingError,
    PromptNotFoundError,
    VersionNotFoundError,
)
from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.prompts import PromptRepository

_logger = structlog.get_logger(__name__)

# The scorers a gating eval grades with when nothing else is specified. The judge needs
# only the gateway (no extra framework), so it's the natural default; a richer config
# (judge + a RAGAS metric) is a per-call override once the API exposes one.
DEFAULT_GATING_SCORERS: list[dict[str, Any]] = [{"scorer": "llm_judge"}]

# The enqueue side: given a freshly-created run id, put it on the eval queue.
EvalSubmit = Callable[[uuid.UUID], None]

# Eval runs per version are low-volume (a handful of re-runs), so the history list caps at a
# fixed depth newest-first rather than paginating — far simpler, and enough for the audit view.
DEFAULT_RUN_HISTORY_LIMIT = 50


@dataclass(frozen=True)
class DatasetItemInput:
    """One golden-set case as supplied at the API boundary (mapped to a ``DatasetItem``)."""

    input: str
    reference: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class EvalStatusView:
    """A version's latest eval state, derived from its most recent run (never stored).

    ``status`` is the run lifecycle: ``unevaluated`` (no run), ``pending``/``running`` (in
    flight), ``completed`` (scores ready in ``summary``), or ``failed`` (the eval itself
    errored). The promotion *verdict* (passed/failed against the floor) is the gate's job,
    computed from ``summary`` at promote time — not conflated into this engine status.
    """

    prompt_version_id: uuid.UUID
    version_number: int
    status: str
    latest_run_id: uuid.UUID | None
    summary: dict[str, Any] | None


class EvalService:
    """Datasets, golden-set wiring, eval triggering, and derived eval status."""

    def __init__(
        self,
        eval_repo: EvalRepository,
        prompt_repo: PromptRepository,
        *,
        submit_eval: EvalSubmit,
        default_scorers: list[dict[str, Any]] | None = None,
    ) -> None:
        self._evals = eval_repo
        self._prompts = prompt_repo
        self._submit_eval = submit_eval
        self._default_scorers = (
            default_scorers if default_scorers is not None else DEFAULT_GATING_SCORERS
        )

    # ---------------------------------------------------------------- datasets
    def create_dataset(
        self, *, name: str, description: str | None, items: list[DatasetItemInput]
    ) -> Dataset:
        """Create a golden set and its items in one transaction."""
        if self._evals.get_dataset_by_name(name) is not None:
            raise DatasetAlreadyExistsError(name)
        dataset = Dataset(
            name=name,
            description=description,
            items=[
                DatasetItem(input=i.input, reference=i.reference, item_metadata=i.metadata)
                for i in items
            ],
        )
        self._evals.add_dataset(dataset)
        self._evals.flush()
        return dataset

    def get_dataset(self, name: str) -> Dataset:
        """Fetch a dataset (with items) by name, or fail with a 404-mapped error."""
        dataset = self._evals.get_dataset_by_name(name)
        if dataset is None:
            raise DatasetNotFoundError(name)
        return dataset

    def list_datasets(self) -> list[tuple[Dataset, int]]:
        """All golden sets with their item counts, for the browse view."""
        return self._evals.list_datasets()

    def update_dataset(
        self, *, name: str, description: str | None, items: list[DatasetItemInput]
    ) -> Dataset:
        """Replace a golden set's description and *all* its cases wholesale (ADR 0024).

        We deliberately do not patch case-by-case: the PUT body is the full desired state, so
        reassigning ``dataset.items`` lets the delete-orphan cascade drop the old cases and insert
        the new ones in one transaction. Historical eval *results* survive — ``EvalRun`` and
        ``ScoreRecord`` reference items with ``ON DELETE SET NULL``, not cascade.
        """
        dataset = self.get_dataset(name)
        dataset.description = description
        dataset.items = [
            DatasetItem(input=i.input, reference=i.reference, item_metadata=i.metadata)
            for i in items
        ]
        # Replacing the items collection dirties the child rows, not the datasets row, so the
        # ``onupdate=now()`` on updated_at wouldn't fire for a cases-only edit. Touch it explicitly
        # so "last edited" reflects case changes too. (now() is the txn timestamp — fine here.)
        dataset.updated_at = func.now()
        self._evals.flush()
        _logger.info("dataset_updated", dataset=name, items=len(items))
        return dataset

    def delete_dataset(self, name: str) -> None:
        """Delete a golden set — unless a prompt still gates on it (ADR 0024).

        Fail-closed: if any prompt's ``golden_set_id`` points here, refuse with the offending
        names rather than nulling out their gate behind their back. The caller detaches first.
        """
        dataset = self.get_dataset(name)
        in_use_by = self._prompts.names_using_golden_set(dataset.id)
        if in_use_by:
            raise DatasetInUseError(name, in_use_by)
        self._evals.delete_dataset(dataset)
        self._evals.flush()
        _logger.info("dataset_deleted", dataset=name)

    def attach_golden_set(self, *, prompt_name: str, dataset_name: str) -> Prompt:
        """Point a prompt at the golden set it must clear to be promoted."""
        prompt = self._require_prompt(prompt_name)
        dataset = self._evals.get_dataset_by_name(dataset_name)
        if dataset is None:
            raise DatasetNotFoundError(dataset_name)
        if not dataset.items:
            raise EmptyGoldenSetError(dataset_name)
        prompt.golden_set_id = dataset.id
        self._prompts.flush()
        _logger.info("golden_set_attached", prompt=prompt_name, dataset=dataset_name)
        return prompt

    def detach_golden_set(self, *, prompt_name: str) -> Prompt:
        """Clear a prompt's golden set, leaving it with no promotion gate until one is reattached.

        Detaching is what lets the now-unused set be deleted (the delete guard, ADR 0024).
        """
        prompt = self._require_prompt(prompt_name)
        prompt.golden_set_id = None
        self._prompts.flush()
        _logger.info("golden_set_detached", prompt=prompt_name)
        return prompt

    # ------------------------------------------------------------- triggering
    def trigger_on_create(self, prompt: Prompt, version: PromptVersion) -> EvalRun | None:
        """Enqueue a gating eval for a just-created version, or ``None`` if no golden set.

        Called from prompt/version creation: a version is evaluated *eagerly* so its verdict
        usually exists by the time anyone tries to promote it. No golden set → nothing to
        grade against → no-op (promotion will be refused later until one is attached).
        """
        if prompt.golden_set_id is None:
            return None
        return self._enqueue_eval(version.id, prompt.golden_set_id)

    def evaluate_version(self, *, prompt_name: str, version_number: int) -> EvalRun:
        """Manually (re-)trigger a gating eval for one version (the explicit endpoint)."""
        prompt = self._require_prompt(prompt_name)
        version = self._require_version(prompt, prompt_name, version_number)
        if prompt.golden_set_id is None:
            raise GoldenSetMissingError(prompt_name)
        return self._enqueue_eval(version.id, prompt.golden_set_id)

    # ------------------------------------------------------------------ reads
    def version_eval_status(self, *, prompt_name: str, version_number: int) -> EvalStatusView:
        """Derive a version's eval state from its most recent run (see :class:`EvalStatusView`)."""
        prompt = self._require_prompt(prompt_name)
        version = self._require_version(prompt, prompt_name, version_number)
        latest = self._evals.latest_run_for_version(version.id)
        return EvalStatusView(
            prompt_version_id=version.id,
            version_number=version.version_number,
            status="unevaluated" if latest is None else latest.status,
            latest_run_id=latest.id if latest is not None else None,
            summary=latest.summary if latest is not None else None,
        )

    def list_version_runs(
        self, *, prompt_name: str, version_number: int, limit: int = DEFAULT_RUN_HISTORY_LIMIT
    ) -> list[EvalRun]:
        """A version's eval runs, newest first — the audit history behind the latest status."""
        prompt = self._require_prompt(prompt_name)
        version = self._require_version(prompt, prompt_name, version_number)
        return self._evals.list_runs_for_version(version.id, limit=limit)

    def latest_completed_run(self, prompt_version_id: uuid.UUID) -> EvalRun | None:
        """The most recent completed run for a version (the gate's source of scores)."""
        return self._evals.latest_completed_run_for_version(prompt_version_id)

    def latest_run(self, prompt_version_id: uuid.UUID) -> EvalRun | None:
        """The most recent run for a version, any status (to detect an in-flight eval)."""
        return self._evals.latest_run_for_version(prompt_version_id)

    # ----------------------------------------------------------------- shared
    def _enqueue_eval(self, prompt_version_id: uuid.UUID, dataset_id: uuid.UUID) -> EvalRun:
        """Create a pending run for (version, golden set) and hand it to the enqueue side."""
        run = EvalRun(
            prompt_version_id=prompt_version_id,
            dataset_id=dataset_id,
            scorer_config=list(self._default_scorers),
            status="pending",
        )
        self._evals.add_run(run)
        self._evals.flush()  # populate run.id before we enqueue it
        self._submit_eval(run.id)
        _logger.info(
            "eval_enqueued", eval_run_id=str(run.id), prompt_version_id=str(prompt_version_id)
        )
        return run

    def _require_prompt(self, name: str) -> Prompt:
        prompt = self._prompts.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)
        return prompt

    @staticmethod
    def _require_version(prompt: Prompt, name: str, version_number: int) -> PromptVersion:
        version = next((v for v in prompt.versions if v.version_number == version_number), None)
        if version is None:
            raise VersionNotFoundError(name, version_number)
        return version
