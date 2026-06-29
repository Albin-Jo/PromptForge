"""ORM models for the prompt registry — the platform's system of record.

The design rests on the *identity / content / pointer* split (ADR notes, Sprint 2):

- :class:`Prompt` is stable **identity** — a named thing that survives every edit.
- :class:`PromptVersion` is frozen **content** — an append-only snapshot. Code
  never ``UPDATE``s a version's content; a change means a new row. Immutability is
  enforced by the repository layer simply never offering an update path.
- :class:`Label` is a mutable **pointer** ("production", "staging") from a prompt
  to one of its versions. Moving the pointer *is* a deployment.

These are persistence entities, not API DTOs — Pydantic models stay out of this
layer (CLAUDE.md: keep DTOs separate from DB entities).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.db.base import Base


class Prompt(Base):
    """A named prompt: stable identity, owns an append-only history of versions."""

    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Human-readable slug used for lookups (the SDK fetches by name, not UUID).
    # UNIQUE backs an index, so name lookups are indexed without a second index.
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # The golden set this prompt is gated against (Sprint 11). NULL = no quality bar
    # configured yet; promoting to the gated label is refused until one is attached
    # (the "CI for prompts" discipline). SET NULL so deleting a dataset un-gates the
    # prompt rather than orphaning the pointer. No relationship() on purpose — the
    # promotion gate only needs the id (to create an eval run), and keeping it a bare
    # FK avoids a cross-module mapper dependency on the eval models.
    golden_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["PromptVersion"]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version_number",
    )
    labels: Mapped[list["Label"]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan"
    )


class PromptVersion(Base):
    """An immutable snapshot of a prompt's content at a point in its history."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        # version_number is monotonic *per prompt* (each prompt has its own 1,2,3…).
        # This constraint makes a duplicate number impossible even under a racy
        # "compute max+1" — the concurrency story revisited in the ACID topic.
        UniqueConstraint(
            "prompt_id", "version_number", name="uq_prompt_versions_prompt_id_version_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column()
    # Lineage: which version this descended from. NULL for v1. Linear for v0.1;
    # the self-FK leaves room for branching later without building it now.
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str] = mapped_column(Text)
    # The variable contract: the names this template declares. Validated at create
    # time to match the template's {{placeholders}} exactly (ADR 0004). JSONB list
    # of strings; typed/described variables are deferred (learning-backlog).
    input_variables: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    # Optional JSON Schema describing the shape callers should expect the model to
    # return. NULL when the version makes no such promise. Validated as a *valid
    # schema* at create time; validating real model output against it comes later.
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # Optional provider/model/params bag (e.g. model name, temperature) returned
    # alongside the rendered prompt. Free-form for now; the gateway (Phase 3) gives
    # it structure. Named model_settings, not model_config — the latter is reserved
    # by Pydantic v2 and would collide in the DTOs.
    model_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prompt: Mapped["Prompt"] = relationship(back_populates="versions")


class Label(Base):
    """A mutable named pointer from a prompt to one of its versions."""

    __tablename__ = "labels"
    __table_args__ = (
        # One "production" (etc.) per prompt; the pointer moves between versions.
        UniqueConstraint("prompt_id", "name", name="uq_labels_prompt_id_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    # RESTRICT: you cannot delete a version a label still points at — this guards
    # the "what's in production?" pointer from being orphaned.
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    prompt: Mapped["Prompt"] = relationship(back_populates="labels")
    version: Mapped["PromptVersion"] = relationship()
