"""create prompt_version_blocks, block_version_blocks

The composition edges of the dependency graph (Sprint 10 / Phase 9, ADR 0015). A
prompt version (or a block version) pins an ordered list of block versions:

- prompt_version_blocks: prompt version -> pinned block version, by position.
- block_version_blocks:  block version  -> pinned child block version, by position
  (the block→block nesting that makes the graph non-trivial / cycle-capable).

Container FK CASCADEs; the pinned block_version_id is ON DELETE RESTRICT so a version
something composes with can't be deleted out from under it. A UNIQUE (container,
position) keeps ordering deterministic.

Revision ID: a1c9e7b35d82
Revises: f3b8c1d24e60
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c9e7b35d82'
down_revision: Union[str, Sequence[str], None] = 'f3b8c1d24e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'prompt_version_blocks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('prompt_version_id', sa.Uuid(), nullable=False),
        sa.Column('block_version_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['prompt_version_id'], ['prompt_versions.id'],
            name=op.f('fk_prompt_version_blocks_prompt_version_id_prompt_versions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['block_version_id'], ['block_versions.id'],
            name=op.f('fk_prompt_version_blocks_block_version_id_block_versions'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prompt_version_blocks')),
        sa.UniqueConstraint(
            'prompt_version_id', 'position',
            name='uq_prompt_version_blocks_prompt_version_id_position',
        ),
    )
    op.create_index(
        op.f('ix_prompt_version_blocks_prompt_version_id'),
        'prompt_version_blocks', ['prompt_version_id'], unique=False,
    )
    op.create_index(
        op.f('ix_prompt_version_blocks_block_version_id'),
        'prompt_version_blocks', ['block_version_id'], unique=False,
    )
    op.create_table(
        'block_version_blocks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('parent_block_version_id', sa.Uuid(), nullable=False),
        sa.Column('child_block_version_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['parent_block_version_id'], ['block_versions.id'],
            name=op.f('fk_block_version_blocks_parent_block_version_id_block_versions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['child_block_version_id'], ['block_versions.id'],
            name=op.f('fk_block_version_blocks_child_block_version_id_block_versions'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_block_version_blocks')),
        sa.UniqueConstraint(
            'parent_block_version_id', 'position',
            name='uq_block_version_blocks_parent_block_version_id_position',
        ),
    )
    op.create_index(
        op.f('ix_block_version_blocks_parent_block_version_id'),
        'block_version_blocks', ['parent_block_version_id'], unique=False,
    )
    op.create_index(
        op.f('ix_block_version_blocks_child_block_version_id'),
        'block_version_blocks', ['child_block_version_id'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_block_version_blocks_child_block_version_id'), table_name='block_version_blocks'
    )
    op.drop_index(
        op.f('ix_block_version_blocks_parent_block_version_id'), table_name='block_version_blocks'
    )
    op.drop_table('block_version_blocks')
    op.drop_index(
        op.f('ix_prompt_version_blocks_block_version_id'), table_name='prompt_version_blocks'
    )
    op.drop_index(
        op.f('ix_prompt_version_blocks_prompt_version_id'), table_name='prompt_version_blocks'
    )
    op.drop_table('prompt_version_blocks')
