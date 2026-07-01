"""Data access for blocks. No business rules here — just persistence.

Mirrors :mod:`promptforge_api.repositories.prompts`: the repository owns *how* we
talk to the database (including the loading strategy that dodges the N+1 problem);
the service owns *what* an operation means.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from promptforge_api.db.block_models import Block


class BlockRepository:
    """CRUD-ish persistence for :class:`Block` aggregates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, block: Block) -> None:
        """Stage a new block (and any versions attached to it) for insert."""
        self._session.add(block)

    def delete(self, block: Block) -> None:
        """Stage a block for deletion; its versions go via ``delete-orphan`` cascade.

        The service guards against deleting an in-use block first (ADR 0027); the DB's
        ``ON DELETE RESTRICT`` on the composition edges is the backstop. Caller flushes.
        """
        self._session.delete(block)

    def flush(self) -> None:
        """Emit pending INSERTs now so DB-side defaults/constraints take effect."""
        self._session.flush()

    def get_by_name(self, name: str) -> Block | None:
        """Fetch a block with its versions in a single round-trip.

        ``selectinload`` eager-loads the versions in one extra query keyed by the
        block id (not a lazy load per access), and the relationship's ``order_by``
        (version_number) means the service can treat ``block.versions`` as ordered
        history without re-sorting — same shape as ``PromptRepository.get_by_name``.
        """
        stmt = select(Block).where(Block.name == name).options(selectinload(Block.versions))
        return self._session.scalars(stmt).one_or_none()

    def list_all(self) -> list[Block]:
        """List every block (with its versions), newest first — the registry view."""
        stmt = select(Block).order_by(Block.created_at.desc()).options(selectinload(Block.versions))
        return list(self._session.scalars(stmt))
