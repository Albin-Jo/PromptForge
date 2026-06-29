"""create security_scans

The security-scanning system of record (Sprint 12 / Phase 10): one row per scan of a piece of
prompt text, holding the findings (as a JSONB list) rolled up to a single risk_level the
promotion gate reads.

prompt_version_id is nullable on purpose — an ad-hoc scan of pasted text is tied to no version —
and uses SET NULL so a scan's results survive its version being deleted. status mirrors
eval_runs' CHECK-constrained lifecycle; risk_level is a second closed set (none/low/medium/high)
that's NULL until the scan completes.

Revision ID: a3d7f1e9c802
Revises: d2f5a8c1e394
Create Date: 2026-06-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3d7f1e9c802'
down_revision: Union[str, Sequence[str], None] = 'd2f5a8c1e394'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'security_scans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
        sa.Column('scanners', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('risk_level', sa.String(length=16), nullable=True),
        sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f('ck_security_scans_status_valid'),
        ),
        sa.CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('none', 'low', 'medium', 'high')",
            name=op.f('ck_security_scans_risk_level_valid'),
        ),
        sa.ForeignKeyConstraint(
            ['prompt_version_id'], ['prompt_versions.id'],
            name=op.f('fk_security_scans_prompt_version_id_prompt_versions'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_security_scans')),
    )
    op.create_index(
        op.f('ix_security_scans_prompt_version_id'), 'security_scans', ['prompt_version_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_security_scans_prompt_version_id'), table_name='security_scans')
    op.drop_table('security_scans')
