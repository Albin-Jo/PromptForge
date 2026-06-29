"""create users

The human-auth system of record (Sprint 13 / Phase 11): one row per person who can log in,
holding a normalised email, a bcrypt password hash (never the password), and a CHECK-constrained
role. Separate from the static X-API-Key machine credential (ADR 0018) — this table backs only
the JWT/human auth path.

email is UNIQUE (the case-insensitive guarantee, since the service stores it lower-cased) and
that index also serves the login lookup. role is a closed set (admin/editor) pinned by a CHECK,
mirroring the status/risk_level CHECKs elsewhere.

Revision ID: c4e7b2a9d150
Revises: a3d7f1e9c802
Create Date: 2026-06-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e7b2a9d150'
down_revision: Union[str, Sequence[str], None] = 'a3d7f1e9c802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'editor')", name=op.f('ck_users_role_valid')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('users')
