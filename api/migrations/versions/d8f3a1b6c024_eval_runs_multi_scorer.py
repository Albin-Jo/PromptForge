"""eval_runs multi-scorer: scorer_config on eval_runs, scorer_name on scores

Sprint 8 / Phase 6 (part 2). Sprint 7 modelled a run as single-scorer
(eval_runs.scorer_name). A run now grades with *several* scorers at once — e.g. the
LLM judge AND a RAGAS metric (ADR 0012) — so:

- eval_runs.scorer_name (String)  -> eval_runs.scorer_config (JSONB list of specs)
- scores gains scorer_name (String) so each per-item score says which scorer made it.

Pre-release, the tables hold no data, so the column swap on eval_runs is a plain
drop+add (no backfill). downgrade() restores the single-scorer shape exactly.

Revision ID: d8f3a1b6c024
Revises: c7e2a9f4b3d1
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd8f3a1b6c024'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9f4b3d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # eval_runs: single scorer_name -> a scorer_config list. No data to migrate (pre-release),
    # so drop then add. NOT NULL: every run must declare at least one scorer.
    op.drop_column('eval_runs', 'scorer_name')
    op.add_column(
        'eval_runs',
        sa.Column('scorer_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    # scores: record which scorer produced each verdict. NOT NULL — every score has a scorer.
    op.add_column('scores', sa.Column('scorer_name', sa.String(length=255), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scores', 'scorer_name')
    op.drop_column('eval_runs', 'scorer_config')
    op.add_column(
        'eval_runs',
        sa.Column('scorer_name', sa.String(length=255), nullable=False),
    )
