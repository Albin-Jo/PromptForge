"""add golden_set to prompts + create promotion_audits

The promotion gate's schema (Sprint 11 / Phase 8, eval-on-change):

- prompts.golden_set_id: the dataset a prompt is quality-gated against. NULL = no bar
  configured; SET NULL so deleting a dataset un-gates rather than orphaning the pointer.
- promotion_audits: one append-only row per attempt to move the gated label, recording
  whether it promoted or was blocked, by whom, from/to which version, and why (the gate's
  per-metric deltas live in the JSONB detail). Version FKs SET NULL but the *_number
  columns preserve identity after a version is deleted.

Note: eval_status is intentionally NOT a column — it is derived from the latest eval_run
for a version, so PromptVersion stays content-immutable.

Revision ID: d2f5a8c1e394
Revises: a1c9e7b35d82
Create Date: 2026-06-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2f5a8c1e394'
down_revision: Union[str, Sequence[str], None] = 'a1c9e7b35d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('prompts', sa.Column('golden_set_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_prompts_golden_set_id_datasets'),
        'prompts', 'datasets', ['golden_set_id'], ['id'], ondelete='SET NULL',
    )
    op.create_table(
        'promotion_audits',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('prompt_id', sa.Uuid(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('to_version_id', sa.Uuid(), nullable=True),
        sa.Column('to_version_number', sa.Integer(), nullable=False),
        sa.Column('from_version_id', sa.Uuid(), nullable=True),
        sa.Column('from_version_number', sa.Integer(), nullable=True),
        sa.Column('decision', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('actor', sa.String(length=255), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "decision IN ('promoted', 'blocked')",
            name=op.f('ck_promotion_audits_decision_valid'),
        ),
        sa.ForeignKeyConstraint(
            ['prompt_id'], ['prompts.id'],
            name=op.f('fk_promotion_audits_prompt_id_prompts'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['to_version_id'], ['prompt_versions.id'],
            name=op.f('fk_promotion_audits_to_version_id_prompt_versions'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['from_version_id'], ['prompt_versions.id'],
            name=op.f('fk_promotion_audits_from_version_id_prompt_versions'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_promotion_audits')),
    )
    op.create_index(
        op.f('ix_promotion_audits_prompt_id'), 'promotion_audits', ['prompt_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_promotion_audits_prompt_id'), table_name='promotion_audits')
    op.drop_table('promotion_audits')
    op.drop_constraint(
        op.f('fk_prompts_golden_set_id_datasets'), 'prompts', type_='foreignkey'
    )
    op.drop_column('prompts', 'golden_set_id')
