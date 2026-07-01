"""broaden the audit trail: generalize promotion_audits into audit_events

ADR 0028. The promotion trail was the platform's only audit surface; this widens it to record
every agreed action (version create, non-gated label moves, golden-set attach/detach, user create)
alongside the existing promote/block decisions.

Done as an in-place generalization of ``promotion_audits`` (not a new table), because that table
had exactly one reader (``GET /audit-log``) and one writer (the promotion gate):

- rename the table ``promotion_audits`` -> ``audit_events`` (and its constraints/index, to keep the
  DB names in step with the model's naming convention);
- rename ``decision`` -> ``action`` and drop its ``IN ('promoted','blocked')`` CHECK — the action
  vocabulary is now open and enforced in code, not by the DB;
- relax the promotion-only NOT NULLs (``prompt_id``, ``label``, ``to_version_number``, ``reason``)
  so a prompt-less event (e.g. ``user_created``) can be recorded;
- add a ``target`` text column carrying the human-readable subject, so the reader is a plain SELECT
  with no join, and backfill it for the existing promotion rows.

The rows are preserved in place — old promotions simply become ``action='promoted'|'blocked'``
events. Append-only, observational, no retention policy (ADR 0028).

Revision ID: a9f3c1d7e205
Revises: c4e7b2a9d150
Create Date: 2026-07-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9f3c1d7e205'
down_revision: Union[str, Sequence[str], None] = 'c4e7b2a9d150'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('promotion_audits', 'audit_events')

    # Drop the promotion-only CHECK — the action set is now open (enforced in code). Raw SQL by
    # literal name: op.drop_constraint would re-derive the name through the naming convention.
    op.execute('ALTER TABLE audit_events DROP CONSTRAINT ck_promotion_audits_decision_valid')

    # Bring the carried-over constraint/index names in line with the new table name so a future
    # autogenerate diff stays clean (the model uses the convention names for audit_events).
    op.execute('ALTER TABLE audit_events RENAME CONSTRAINT pk_promotion_audits TO pk_audit_events')
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_promotion_audits_prompt_id_prompts TO fk_audit_events_prompt_id_prompts'
    )
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_promotion_audits_to_version_id_prompt_versions TO '
        'fk_audit_events_to_version_id_prompt_versions'
    )
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_promotion_audits_from_version_id_prompt_versions TO '
        'fk_audit_events_from_version_id_prompt_versions'
    )
    op.execute('ALTER INDEX ix_promotion_audits_prompt_id RENAME TO ix_audit_events_prompt_id')

    # decision -> action; widen it (the new verbs like 'golden_set_attached' don't fit String(16))
    # and let it hold an open vocabulary, not just promoted|blocked.
    op.alter_column(
        'audit_events', 'decision', new_column_name='action',
        existing_type=sa.String(length=16), type_=sa.String(length=64), existing_nullable=False,
    )

    # Relax the promotion-only NOT NULLs so non-promotion events can be recorded.
    op.alter_column('audit_events', 'prompt_id', existing_type=sa.Uuid(), nullable=True)
    op.alter_column('audit_events', 'label', existing_type=sa.String(length=255), nullable=True)
    op.alter_column('audit_events', 'to_version_number', existing_type=sa.Integer(), nullable=True)
    op.alter_column('audit_events', 'reason', existing_type=sa.Text(), nullable=True)

    # The human-readable subject of the event — what the Activity page shows in its Target column.
    op.add_column('audit_events', sa.Column('target', sa.Text(), nullable=True))

    # Backfill target for the existing (promotion) rows so the feed reads uniformly. Matches the
    # string the old reader built: "<prompt>:<label> -> v<n>".
    op.execute(
        "UPDATE audit_events SET target = p.name || ':' || audit_events.label || ' → v' || "
        "audit_events.to_version_number::text "
        "FROM prompts p WHERE audit_events.prompt_id = p.id AND audit_events.target IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema.

    Best-effort: re-imposing the NOT NULLs and the decision CHECK will fail if any generalized
    (non-promotion or NULL-bearing) rows exist — you can't squeeze widened data back into the old
    promotion-only shape. A dev/rollback tool, not a production round-trip (ADR 0028).
    """
    op.drop_column('audit_events', 'target')

    op.alter_column('audit_events', 'reason', existing_type=sa.Text(), nullable=False)
    op.alter_column('audit_events', 'to_version_number', existing_type=sa.Integer(), nullable=False)
    op.alter_column('audit_events', 'label', existing_type=sa.String(length=255), nullable=False)
    op.alter_column('audit_events', 'prompt_id', existing_type=sa.Uuid(), nullable=False)

    op.alter_column(
        'audit_events', 'action', new_column_name='decision',
        existing_type=sa.String(length=64), type_=sa.String(length=16), existing_nullable=False,
    )

    op.execute('ALTER INDEX ix_audit_events_prompt_id RENAME TO ix_promotion_audits_prompt_id')
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_audit_events_from_version_id_prompt_versions TO '
        'fk_promotion_audits_from_version_id_prompt_versions'
    )
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_audit_events_to_version_id_prompt_versions TO '
        'fk_promotion_audits_to_version_id_prompt_versions'
    )
    op.execute(
        'ALTER TABLE audit_events RENAME CONSTRAINT '
        'fk_audit_events_prompt_id_prompts TO fk_promotion_audits_prompt_id_prompts'
    )
    op.execute('ALTER TABLE audit_events RENAME CONSTRAINT pk_audit_events TO pk_promotion_audits')

    op.execute(
        "ALTER TABLE audit_events ADD CONSTRAINT ck_promotion_audits_decision_valid "
        "CHECK (decision IN ('promoted', 'blocked'))"
    )
    op.rename_table('audit_events', 'promotion_audits')
