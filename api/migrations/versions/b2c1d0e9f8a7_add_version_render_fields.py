"""add render fields to prompt_versions

Adds the Phase 2 fields a version needs to be rendered into a finished prompt:
- input_variables: the declared variable contract (JSONB list of names)
- output_schema:   optional JSON Schema for the expected model-output shape
- model_settings:  optional provider/model/params bag returned with the prompt

Revision ID: b2c1d0e9f8a7
Revises: 4070df012230
Create Date: 2026-06-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c1d0e9f8a7'
down_revision: Union[str, Sequence[str], None] = '4070df012230'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL with a server-side default so existing rows (and inserts that omit
    # it) get an empty list rather than NULL — the variable contract is "no
    # variables", never "unknown".
    op.add_column(
        'prompt_versions',
        sa.Column(
            'input_variables',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'prompt_versions',
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'prompt_versions',
        sa.Column('model_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('prompt_versions', 'model_settings')
    op.drop_column('prompt_versions', 'output_schema')
    op.drop_column('prompt_versions', 'input_variables')
