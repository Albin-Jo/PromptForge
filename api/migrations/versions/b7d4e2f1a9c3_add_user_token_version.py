"""add users.token_version (revocable tokens)

ADR 0029. Refresh (and access) tokens were stateless and non-revocable: a leaked token for a user
who stays *active* had no server-side kill switch, valid until its TTL. This adds one integer per
user, ``token_version``, stamped into every minted token and compared on every verify. Bumping the
column invalidates all of a user's outstanding tokens at once (revoke / deactivate / role-change),
without a per-token store.

NOT NULL with a server_default of 0 so existing user rows backfill cleanly; a token minted before
this column existed carries no claim and is read as version 0 in code, so it still matches.

Revision ID: b7d4e2f1a9c3
Revises: a9f3c1d7e205
Create Date: 2026-07-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7d4e2f1a9c3'
down_revision: Union[str, Sequence[str], None] = 'a9f3c1d7e205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column(
            'token_version', sa.Integer(), server_default=sa.text('0'), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'token_version')
