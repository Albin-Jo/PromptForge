"""Data access for the evaluation engine — datasets, their items, and eval runs.

Sprint 7/8 defined the eval ORM models and drove runs from tests/Python only; this
repository is the persistence half of the *API* surface that Sprint 11 needs: create a
golden set, and create / look up the eval runs the promotion gate reads. No business
rules here — the service owns *what* an operation means, the repository owns *how* it
talks to the database (the same split as :class:`PromptRepository`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from promptforge_api.db.eval_models import Dataset, DatasetItem, EvalRun


class EvalRepository:
    """Persistence for datasets and eval runs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def flush(self) -> None:
        """Emit pending INSERTs now so DB-side defaults/ids are populated."""
        self._session.flush()

    # ------------------------------------------------------------------ datasets
    def add_dataset(self, dataset: Dataset) -> None:
        """Stage a new dataset (and any items attached via the relationship) for insert."""
        self._session.add(dataset)

    def get_dataset(self, dataset_id: uuid.UUID) -> Dataset | None:
        """Fetch a dataset (with its items) by id."""
        stmt = select(Dataset).where(Dataset.id == dataset_id).options(selectinload(Dataset.items))
        return self._session.scalars(stmt).one_or_none()

    def get_dataset_by_name(self, name: str) -> Dataset | None:
        """Fetch a dataset (with its items) by its unique name."""
        stmt = select(Dataset).where(Dataset.name == name).options(selectinload(Dataset.items))
        return self._session.scalars(stmt).one_or_none()

    def list_datasets(self) -> list[tuple[Dataset, int]]:
        """All datasets with their item counts, name-ordered.

        The browse view needs the count, not the (potentially large) case bodies, so we
        aggregate ``count(items)`` DB-side with an outer join rather than ``selectinload`` +
        ``len`` — the same "don't load bodies to list" choice as ``list_summaries`` for prompts.
        The outer join keeps datasets with zero items (count 0) in the list.
        """
        stmt = (
            select(Dataset, func.count(DatasetItem.id))
            .outerjoin(DatasetItem, DatasetItem.dataset_id == Dataset.id)
            .group_by(Dataset.id)
            .order_by(Dataset.name)
        )
        return [(dataset, count) for dataset, count in self._session.execute(stmt).all()]

    def delete_dataset(self, dataset: Dataset) -> None:
        """Stage a dataset for deletion; its items go too via the delete-orphan cascade."""
        self._session.delete(dataset)

    # ---------------------------------------------------------------- eval runs
    def add_run(self, run: EvalRun) -> None:
        """Stage a new eval run for insert."""
        self._session.add(run)

    def get_run(self, run_id: uuid.UUID) -> EvalRun | None:
        """Fetch a single eval run by id."""
        return self._session.get(EvalRun, run_id)

    def latest_run_for_version(self, prompt_version_id: uuid.UUID) -> EvalRun | None:
        """The most recent eval run for a version, *any* status (to detect a pending eval)."""
        stmt = (
            select(EvalRun)
            .where(EvalRun.prompt_version_id == prompt_version_id)
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).one_or_none()

    def list_runs_for_version(
        self, prompt_version_id: uuid.UUID, *, limit: int
    ) -> list[EvalRun]:
        """A version's eval runs, newest first, capped at ``limit`` (the run-history list).

        The summary rollup lives on the row, so the history needs no per-item ``scores`` load —
        the same "don't load the heavy children to list" choice as ``list_datasets``.
        """
        stmt = (
            select(EvalRun)
            .where(EvalRun.prompt_version_id == prompt_version_id)
            .order_by(EvalRun.created_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def latest_completed_run_for_version(self, prompt_version_id: uuid.UUID) -> EvalRun | None:
        """The most recent *completed* eval run for a version (the gate's source of scores)."""
        stmt = (
            select(EvalRun)
            .where(
                EvalRun.prompt_version_id == prompt_version_id,
                EvalRun.status == "completed",
            )
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).one_or_none()
