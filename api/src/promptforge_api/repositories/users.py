"""Data access for users. No business rules here — just persistence.

Mirrors the other repositories (:mod:`promptforge_api.repositories.blocks` et al.): the
repository owns *how* we talk to the database; the service owns *what* an operation means. The
service is responsible for normalising the email before it reaches here.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptforge_api.db.user_models import User


class UserRepository:
    """CRUD-ish persistence for :class:`User` rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> None:
        """Stage a new user for insert."""
        self._session.add(user)

    def flush(self) -> None:
        """Emit pending INSERTs now so DB-side defaults/constraints take effect."""
        self._session.flush()

    def get_by_email(self, email: str) -> User | None:
        """Fetch a user by (already-normalised) email, or ``None`` if absent."""
        stmt = select(User).where(User.email == email)
        return self._session.scalars(stmt).one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Fetch a user by primary key, or ``None`` if absent."""
        return self._session.get(User, user_id)

    def list_all(self) -> list[User]:
        """Return every user, newest first (email as a stable tiebreaker for equal timestamps)."""
        stmt = select(User).order_by(User.created_at.desc(), User.email.asc())
        return list(self._session.scalars(stmt).all())

    def count_active_admins(self, *, exclude: uuid.UUID | None = None) -> int:
        """Count active admins, optionally excluding one id (the self-lockout guard, ADR 0029)."""
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True), User.role == "admin")
        )
        if exclude is not None:
            stmt = stmt.where(User.id != exclude)
        return self._session.scalar(stmt) or 0
