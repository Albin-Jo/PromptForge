"""create blocks, block_versions

The block half of composable prompts (Sprint 10 / Phase 9). Mirrors the
prompts / prompt_versions shape: a Block is typed identity, a BlockVersion is an
immutable, per-block-numbered snapshot.

- blocks: name (unique), role (CHECK-constrained closed set), description.
- block_versions: per-block version_number (UNIQUE with block_id), self-FK
  parent_version_id for linear lineage, content (mustache template), input_variables.

The composition *edges* (which blocks a prompt/block includes) land in a follow-up
migration so these tables can be created and tested on their own first.

Revision ID: f3b8c1d24e60
Revises: e1a47c2b9f53
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3b8c1d24e60'
down_revision: Union[str, Sequence[str], None] = 'e1a47c2b9f53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'blocks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "role IN ('role', 'context', 'guardrails', 'output_format', 'other')",
            name=op.f('ck_blocks_role_valid'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_blocks')),
        sa.UniqueConstraint('name', name=op.f('uq_blocks_name')),
    )
    op.create_table(
        'block_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('block_id', sa.Uuid(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('parent_version_id', sa.Uuid(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column(
            'input_variables',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['block_id'], ['blocks.id'],
            name=op.f('fk_block_versions_block_id_blocks'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['parent_version_id'], ['block_versions.id'],
            name=op.f('fk_block_versions_parent_version_id_block_versions'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_block_versions')),
        sa.UniqueConstraint(
            'block_id', 'version_number',
            name=op.f('uq_block_versions_block_id_version_number'),
        ),
    )
    op.create_index(
        op.f('ix_block_versions_block_id'), 'block_versions', ['block_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_block_versions_block_id'), table_name='block_versions')
    op.drop_table('block_versions')
    op.drop_table('blocks')
