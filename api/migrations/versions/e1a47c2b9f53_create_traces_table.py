"""create traces

Sprint 8 / Phase 7 (start). One row per execution, linked back to the prompt version
that produced it, with tokens, computed cost, latency, and outcome — the system of
record for observability. Emission + async ingestion land in Sprint 9; this just
defines the table (+ the config-driven pricing that fills cost_usd).

Denormalised prompt_id sits alongside the version FK for per-prompt cost attribution
without a join. Both prompt FKs SET NULL so a trace's historical spend survives the
prompt/version being deleted. created_at is indexed: traces are queried by recent
time window (partitioning is the deferred scaling lever).

Revision ID: e1a47c2b9f53
Revises: d8f3a1b6c024
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1a47c2b9f53'
down_revision: Union[str, Sequence[str], None] = 'd8f3a1b6c024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'traces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('prompt_id', sa.Uuid(), nullable=True),
        sa.Column('prompt_version_id', sa.Uuid(), nullable=True),
        sa.Column('request_id', sa.String(length=255), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('provider', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=255), nullable=False),
        sa.Column('provider_model', sa.String(length=255), nullable=True),
        sa.Column('input', sa.Text(), nullable=True),
        sa.Column('output', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error_type', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f('ck_traces_status_valid')),
        sa.ForeignKeyConstraint(
            ['prompt_id'], ['prompts.id'],
            name=op.f('fk_traces_prompt_id_prompts'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['prompt_version_id'], ['prompt_versions.id'],
            name=op.f('fk_traces_prompt_version_id_prompt_versions'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_traces')),
    )
    op.create_index(op.f('ix_traces_prompt_id'), 'traces', ['prompt_id'], unique=False)
    op.create_index(
        op.f('ix_traces_prompt_version_id'), 'traces', ['prompt_version_id'], unique=False
    )
    op.create_index(op.f('ix_traces_request_id'), 'traces', ['request_id'], unique=False)
    op.create_index(op.f('ix_traces_created_at'), 'traces', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_traces_created_at'), table_name='traces')
    op.drop_index(op.f('ix_traces_request_id'), table_name='traces')
    op.drop_index(op.f('ix_traces_prompt_version_id'), table_name='traces')
    op.drop_index(op.f('ix_traces_prompt_id'), table_name='traces')
    op.drop_table('traces')
