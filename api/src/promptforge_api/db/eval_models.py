"""ORM models for the evaluation engine — the system of record for *quality*.

Where the registry models (``db/models.py``) record *what a prompt is*, these record
*how good its outputs are*. Four entities, in two pairs:

- **The golden set.** :class:`Dataset` is a named collection of test cases;
  :class:`DatasetItem` is one case — an input and (optionally) a reference answer.
  This is the curated set an eval runs against (learning-backlog: golden sets).
- **A scored run.** :class:`EvalRun` is one execution of a scorer over outputs;
  :class:`Score` is that scorer's verdict on a single item. ``EvalRun`` owns its
  scores, so "this run scored 7/10 items as passing" is a single aggregate query.

This sprint only *defines and persists* these (the demo scores one output). Driving
a full run over a dataset via Celery, and tying a run to a prompt version's outputs,
land in Sprint 8 — which is why ``dataset_id`` and ``prompt_version_id`` are nullable
here: an ad-hoc single-output score has neither yet.

Persistence entities, not API DTOs (CLAUDE.md). The ``Score`` dataclass in
:mod:`promptforge_api.evals.scorer` is the in-memory verdict; :class:`ScoreRecord`
here is its durable row — same idea, different layer. The two carry different names on
purpose, so code that touches both (Sprint 8) never has to alias one away.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.db.base import Base


class Dataset(Base):
    """A named golden set: the fixed cases an evaluation runs against."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Human-readable handle; UNIQUE backs lookups by name (as with prompts).
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["DatasetItem"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetItem(Base):
    """One test case: an input, and optionally the reference answer to grade against."""

    __tablename__ = "dataset_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    # The case input — what the prompt/model is given.
    input: Mapped[str] = mapped_column(Text)
    # The expected/gold answer. NULL = reference-free case (judge intrinsic quality).
    reference: Mapped[str | None] = mapped_column(Text, default=None)
    # Per-case extras (tags, source, grading hints). Named item_metadata, not
    # metadata — the latter is reserved on the declarative class (it's Base.metadata).
    item_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="items")


class EvalRun(Base):
    """One execution of a scorer over some outputs; owns the resulting scores."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        # The lifecycle is a closed set; a CHECK keeps a typo'd or invented status out
        # of the data of record rather than discovering it when a query filters on it.
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The golden set graded. SET NULL (not CASCADE): deleting a dataset shouldn't
    # erase the historical *results* of having run against it. NULL for an ad-hoc
    # single-output score with no dataset.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), default=None, index=True
    )
    # Which prompt version's outputs were graded. NULL until run-wiring (Sprint 8)
    # ties a run to a version; SET NULL keeps a run's results after a version is gone.
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None, index=True
    )
    # The scorers this run grades with, as a list of {"scorer": name, "params": {...}} specs
    # (Sprint 8 / ADR 0012). A run may use several at once — e.g. the LLM judge *and* a RAGAS
    # metric — and the worker's registry turns each name into a live Scorer. Storing the config
    # (not just a name) keeps a run self-describing: it records exactly how it was graded.
    # Replaces Sprint 7's single scorer_name now that a run is multi-scorer.
    scorer_config: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Lifecycle: pending → running → completed | failed (pinned by the CHECK above).
    # server_default backs the constraint for any non-ORM insert; the Python default
    # keeps a freshly built, not-yet-flushed run readable in memory.
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    # Aggregate verdict over the run (pass_rate, mean_value, count). NULL until the
    # run completes; the per-item truth always lives in the scores rows.
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    scores: Mapped[list["ScoreRecord"]] = relationship(
        back_populates="eval_run", cascade="all, delete-orphan"
    )


class ScoreRecord(Base):
    """A single scorer verdict on one output — the durable form of a Score dataclass."""

    __tablename__ = "scores"
    __table_args__ = (
        # value mirrors Score.value, which is normalised to [0,1]; a CHECK stops a
        # buggy writer storing an out-of-scale number that would skew every aggregate.
        CheckConstraint("value >= 0 AND value <= 1", name="value_unit_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True
    )
    # Which scorer produced this verdict (Scorer.name). A run graded by several scorers (judge
    # + a RAGAS metric) writes one score row per (item, scorer); this column keeps them apart so
    # an aggregate can be computed per scorer. Added Sprint 8 alongside EvalRun.scorer_config.
    scorer_name: Mapped[str] = mapped_column(String(255))
    # The case graded, when the run came from a dataset. SET NULL so a score survives
    # its item being removed; NULL for an ad-hoc single-output score.
    dataset_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_items.id", ondelete="SET NULL"), default=None, index=True
    )
    # Normalised quality in [0,1] (mirrors Score.value) — comparable across scorers.
    value: Mapped[float] = mapped_column(Float)
    # The pass/fail gate the scorer derived (mirrors Score.passed).
    passed: Mapped[bool] = mapped_column(Boolean)
    rationale: Mapped[str] = mapped_column(Text)
    # Scorer-specific extras (judge rating, model, threshold…). Named score_metadata
    # for the same reserved-attribute reason as DatasetItem.item_metadata.
    score_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    eval_run: Mapped["EvalRun"] = relationship(back_populates="scores")
