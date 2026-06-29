"""ORM models for composable prompts — the reusable building blocks (Sprint 10).

The flagship lets a prompt be **assembled from typed, versioned blocks** instead of
one long string. These models add the *block* half of that, mirroring the registry's
identity / content split (``db/models.py``) exactly so the mental model carries over:

- :class:`Block` is stable **identity** — a named, typed, reusable fragment
  (a shared ``guardrails`` block, a ``role`` block) that survives every edit.
- :class:`BlockVersion` is frozen **content** — an append-only snapshot, immutable
  by the same omission-of-an-update-path discipline the prompt versions use.

A block's *role* (``role`` / ``context`` / ``guardrails`` / ``output_format`` /
``other``) lives on the **identity**, not the version: a block's kind is part of
*what it is*, and shouldn't flip from edit to edit. The *composition* edges that wire
a prompt (or a block) to the blocks it includes are modelled separately, alongside
the dependency-graph work — kept out of here so the block tables can land and be
tested on their own first.

Persistence entities, not API DTOs (CLAUDE.md): Pydantic stays at the boundary.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.db.base import Base

# The closed set of block roles. A block is *typed* so the editor (and a human) can
# reason about composition — guardrails wrap, a role sets persona, context grounds,
# output_format constrains shape. "other" is the escape hatch. Note "role" is both the
# dimension's name and one of its values (a block that defines the assistant's role).
BLOCK_ROLES = ("role", "context", "guardrails", "output_format", "other")


class Block(Base):
    """A named, typed prompt fragment: stable identity, append-only version history."""

    __tablename__ = "blocks"
    __table_args__ = (
        # role is a closed set; a CHECK keeps a typo'd/invented role out of the data
        # of record (same discipline as eval_runs.status), rather than discovering it
        # when composition filters on it.
        CheckConstraint(
            "role IN ('role', 'context', 'guardrails', 'output_format', 'other')",
            name="role_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Human-readable slug used for lookups, exactly as prompts are fetched by name.
    # UNIQUE backs an index, so name lookups are indexed without a second index.
    name: Mapped[str] = mapped_column(String(255), unique=True)
    # The block's kind (see BLOCK_ROLES). On the identity because it describes the
    # block itself, not a single revision of its text.
    role: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["BlockVersion"]] = relationship(
        back_populates="block",
        cascade="all, delete-orphan",
        order_by="BlockVersion.version_number",
    )


class BlockVersion(Base):
    """An immutable snapshot of a block's content at a point in its history."""

    __tablename__ = "block_versions"
    __table_args__ = (
        # version_number is monotonic *per block* (each block has its own 1, 2, 3…),
        # mirroring prompt_versions; the UNIQUE makes a duplicate number impossible.
        UniqueConstraint(
            "block_id", "version_number", name="uq_block_versions_block_id_version_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blocks.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column()
    # Lineage: which version this descended from. NULL for v1. Linear for v0.1; the
    # self-FK leaves room for branching later without building it (as with prompts).
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("block_versions.id", ondelete="SET NULL"), default=None
    )
    # The fragment's mustache template — same renderer, same data-not-code stance as a
    # prompt version (ADR 0004). A block carries no output_schema/model_settings: it's a
    # *part* of a prompt, not a standalone thing that calls a model.
    content: Mapped[str] = mapped_column(Text)
    # The variables this fragment declares, validated to match its {{placeholders}}
    # exactly at create time (ADR 0004). A composed prompt's render contract is the
    # union of its own variables and those of every block it (transitively) includes.
    input_variables: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    block: Mapped["Block"] = relationship(back_populates="versions")
