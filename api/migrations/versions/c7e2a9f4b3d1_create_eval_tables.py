"""create datasets, dataset_items, eval_runs, scores

The evaluation engine's system of record (Sprint 7 / Phase 6):
- datasets / dataset_items: golden sets — named collections of test cases.
- eval_runs / scores:        a scored run and its per-output verdicts.

dataset_id and prompt_version_id on eval_runs are nullable on purpose: an ad-hoc
single-output score (this sprint's demo) is tied to neither yet. FKs out of the
result tables use SET NULL so historical results survive a dataset/version being
deleted; a run CASCADEs to its own scores.

Revision ID: c7e2a9f4b3d1
Revises: b2c1d0e9f8a7
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c7e2a9f4b3d1'
down_revision: Union[str, Sequence[str], None] = 'b2c1d0e9f8a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'datasets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_datasets')),
        sa.UniqueConstraint('name', name=op.f('uq_datasets_name')),
    )
    op.create_table(
        'dataset_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('input', sa.Text(), nullable=False),
        sa.Column('reference', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['datasets.id'],
            name=op.f('fk_dataset_items_dataset_id_datasets'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_items')),
    )
    op.create_index(op.f('ix_dataset_items_dataset_id'), 'dataset_items', ['dataset_id'], unique=False)
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=True),
        sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
        sa.Column('scorer_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f('ck_eval_runs_status_valid'),
        ),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['datasets.id'],
            name=op.f('fk_eval_runs_dataset_id_datasets'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['prompt_version_id'], ['prompt_versions.id'],
            name=op.f('fk_eval_runs_prompt_version_id_prompt_versions'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_runs')),
    )
    op.create_index(op.f('ix_eval_runs_dataset_id'), 'eval_runs', ['dataset_id'], unique=False)
    op.create_index(
        op.f('ix_eval_runs_prompt_version_id'), 'eval_runs', ['prompt_version_id'], unique=False
    )
    op.create_table(
        'scores',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('eval_run_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_item_id', sa.Uuid(), nullable=True),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('value >= 0 AND value <= 1', name=op.f('ck_scores_value_unit_range')),
        sa.ForeignKeyConstraint(
            ['eval_run_id'], ['eval_runs.id'],
            name=op.f('fk_scores_eval_run_id_eval_runs'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['dataset_item_id'], ['dataset_items.id'],
            name=op.f('fk_scores_dataset_item_id_dataset_items'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scores')),
    )
    op.create_index(op.f('ix_scores_eval_run_id'), 'scores', ['eval_run_id'], unique=False)
    op.create_index(op.f('ix_scores_dataset_item_id'), 'scores', ['dataset_item_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_scores_dataset_item_id'), table_name='scores')
    op.drop_index(op.f('ix_scores_eval_run_id'), table_name='scores')
    op.drop_table('scores')
    op.drop_index(op.f('ix_eval_runs_prompt_version_id'), table_name='eval_runs')
    op.drop_index(op.f('ix_eval_runs_dataset_id'), table_name='eval_runs')
    op.drop_table('eval_runs')
    op.drop_index(op.f('ix_dataset_items_dataset_id'), table_name='dataset_items')
    op.drop_table('dataset_items')
    op.drop_table('datasets')
