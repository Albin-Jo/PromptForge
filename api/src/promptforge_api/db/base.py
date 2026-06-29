"""SQLAlchemy declarative base and shared metadata conventions.

Every ORM model inherits from :class:`Base`, so ``Base.metadata`` is the single
catalog of tables that Alembic diffs against to autogenerate migrations.

The naming convention makes constraint and index names **deterministic** rather
than letting Postgres assign its own. Without it, a migration that drops a
constraint has to guess the auto-assigned name; with it, names are predictable
and stable across environments, which keeps ``downgrade()`` reversible.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every PromptForge ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
