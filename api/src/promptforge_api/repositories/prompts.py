"""Data access for prompts. No business rules here — just persistence.

The repository owns *how* we talk to the database; the service owns *what* the
operation means. Keeping reads here (with their loading strategy) means the
service never has to think about SQL or the N+1 problem.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from promptforge_api.db.models import Label, Prompt, PromptVersion


@dataclass(frozen=True, slots=True)
class PromptSummary:
    """A lightweight list-view row: prompt identity plus version counts.

    Deliberately omits version *content* — the list page only needs to enumerate prompts,
    so we aggregate version numbers DB-side rather than load every version body.
    """

    name: str
    description: str | None
    latest_version: int | None
    version_count: int
    created_at: datetime
    updated_at: datetime


class PromptRepository:
    """CRUD-ish persistence for :class:`Prompt` aggregates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, prompt: Prompt) -> None:
        """Stage a new prompt (and any versions attached to it) for insert."""
        self._session.add(prompt)

    def add_label(self, label: Label) -> None:
        """Stage a new label pointer for insert."""
        self._session.add(label)

    def flush(self) -> None:
        """Emit pending INSERTs now so DB-side defaults/constraints take effect."""
        self._session.flush()

    def list_summaries(self) -> list[PromptSummary]:
        """List all prompts (name-ordered) with version aggregates, no version bodies.

        The version count + latest number are computed with a grouped subquery and an
        outer join, so a prompt with no versions still appears (counts as 0 / None) and
        we never load a single version row. DB-side aggregation, consistent with the
        metrics read-model approach (ADR 0014).
        """
        agg = (
            select(
                PromptVersion.prompt_id.label("prompt_id"),
                func.max(PromptVersion.version_number).label("latest_version"),
                func.count().label("version_count"),
            )
            .group_by(PromptVersion.prompt_id)
            .subquery()
        )
        stmt = (
            select(
                Prompt.name,
                Prompt.description,
                agg.c.latest_version,
                func.coalesce(agg.c.version_count, 0),
                Prompt.created_at,
                Prompt.updated_at,
            )
            .outerjoin(agg, Prompt.id == agg.c.prompt_id)
            .order_by(Prompt.name)
        )
        return [
            PromptSummary(
                name=name,
                description=description,
                latest_version=latest_version,
                version_count=version_count,
                created_at=created_at,
                updated_at=updated_at,
            )
            for name, description, latest_version, version_count, created_at, updated_at in (
                self._session.execute(stmt).all()
            )
        ]

    def get_by_name(self, name: str) -> Prompt | None:
        """Fetch a prompt with its versions in a single round-trip.

        ``selectinload`` eager-loads the versions in one extra query keyed by the
        prompt id, instead of a lazy load per access — the difference between two
        queries and the N+1 problem once this returns lists of prompts. The
        relationship's ``order_by`` (version_number) means the service can treat
        ``prompt.versions`` as ordered history without re-sorting.
        """
        stmt = select(Prompt).where(Prompt.name == name).options(selectinload(Prompt.versions))
        return self._session.scalars(stmt).one_or_none()

    def names_using_golden_set(self, dataset_id: uuid.UUID) -> list[str]:
        """Names of prompts whose golden set points at this dataset (the delete-guard lookup).

        A bare ``name`` projection — the delete guard only needs to know *whether* and *which*
        prompts reference the dataset, not load whole aggregates. Name-ordered for a stable,
        human-readable error message.
        """
        stmt = select(Prompt.name).where(Prompt.golden_set_id == dataset_id).order_by(Prompt.name)
        return list(self._session.scalars(stmt).all())

    def get_label(self, prompt_id: uuid.UUID, name: str) -> Label | None:
        """Fetch a single label pointer (with the version it points at) by name."""
        stmt = (
            select(Label)
            .where(Label.prompt_id == prompt_id, Label.name == name)
            .options(selectinload(Label.version))
        )
        return self._session.scalars(stmt).one_or_none()
