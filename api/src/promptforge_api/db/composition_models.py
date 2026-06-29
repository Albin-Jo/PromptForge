"""ORM models for prompt composition — the edges of the dependency graph (Sprint 10).

ADR 0015: a composition pins exact block *versions* in an ordered list. There are two
edge tables, one per container kind:

- :class:`PromptVersionBlock` — a prompt version includes block versions (the top
  level of a composition).
- :class:`BlockVersionBlock` — a block version includes other block versions
  (nesting). This is the only place a **block→block** edge exists, and therefore the
  only place a cycle could form — which is why cycle detection guards block-version
  creation, not prompt-version creation (a prompt is always a graph sink).

Both tables are ordered by ``position`` and pin an immutable ``block_version_id`` with
``ON DELETE RESTRICT`` — you cannot delete a block version something still composes
with (the referential guard mirrors the label→version RESTRICT in ADR 0005). The
container side CASCADEs: dropping a (rare) version drops its composition rows with it.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base


class PromptVersionBlock(Base):
    """One ordered reference from a prompt version to a pinned block version."""

    __tablename__ = "prompt_version_blocks"
    __table_args__ = (
        # Ordering is deterministic: at most one block per position in a composition.
        UniqueConstraint(
            "prompt_version_id",
            "position",
            name="uq_prompt_version_blocks_prompt_version_id_position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"), index=True
    )
    # Pinned: an exact, immutable block version (ADR 0015). RESTRICT guards it from
    # deletion while a prompt still composes with it.
    block_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("block_versions.id", ondelete="RESTRICT"), index=True
    )
    # 0-based order of this block within the prompt's composition.
    position: Mapped[int] = mapped_column(Integer)


class BlockVersionBlock(Base):
    """One ordered reference from a block version to a pinned child block version."""

    __tablename__ = "block_version_blocks"
    __table_args__ = (
        UniqueConstraint(
            "parent_block_version_id",
            "position",
            name="uq_block_version_blocks_parent_block_version_id_position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_block_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("block_versions.id", ondelete="CASCADE"), index=True
    )
    # Pinned child (ADR 0015); RESTRICT guards it from deletion while referenced.
    child_block_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("block_versions.id", ondelete="RESTRICT"), index=True
    )
    # 0-based order of this child within the parent block's composition.
    position: Mapped[int] = mapped_column(Integer)
