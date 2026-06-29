"""ORM model for human users — the system of record for *who* (Sprint 13 / Phase 11).

Distinct from the static ``X-API-Key`` machine credential (see
:mod:`promptforge_api.security`): an API key identifies a calling *service*, a :class:`User`
identifies a *person* who logs in and carries a role. The two auth paths stay separate (ADR
0018) — this table backs only the human/JWT path.

A deliberately lean shape for v0.1: identity, a hashed password, and a two-value role. No
profile, no per-resource grants, no soft-delete — just enough for login + a who-may-edit gate.
RBAC and multi-tenancy are post-v0.1 (overview §4).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.db.base import Base

# The closed set of roles. ``admin`` may do everything (incl. create users + promote);
# ``editor`` may author prompts/versions but not promote or manage users (enforced in the
# router/authz layer, Task 3). Pinned by a CHECK so an invented role can't reach the data.
ROLES = ("admin", "editor")


class User(Base):
    """A person who can log in: email + hashed password + a role."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'editor')", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Login identifier, stored already lower-cased/normalised by the service so the UNIQUE
    # index is the case-insensitive uniqueness guarantee (no two "Alice@x" and "alice@x").
    # 320 is the RFC-5321 maximum address length. UNIQUE backs the lookup index.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # The bcrypt hash, never the password. bcrypt emits 60 chars; String(255) leaves room
    # for a future scheme (e.g. argon2) without a migration.
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    # Soft on/off switch: a disabled user keeps their row (and audit trail) but can't log in.
    # server_default backs non-ORM inserts; the Python default keeps an in-memory user truthy.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
