"""Alembic migration environment.

Two deviations from the stock template, both deliberate:

- The database URL comes from our :class:`Settings` (one twelve-factor source of
  truth) rather than being hard-coded in ``alembic.ini`` — no DSN/secret in the
  ini file.
- ``target_metadata`` is our :class:`Base` metadata with every model imported, so
  ``alembic revision --autogenerate`` can diff the live database against the
  models. We still *read* every generated migration before applying it.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import promptforge_api.db.audit_models  # noqa: F401

# Importing the model modules registers every table on Base.metadata. The
# noqa keeps the lint-only "unused import" off imports we need for their side
# effect of populating the metadata.
import promptforge_api.db.block_models  # noqa: F401
import promptforge_api.db.composition_models  # noqa: F401
import promptforge_api.db.eval_models  # noqa: F401
import promptforge_api.db.models  # noqa: F401
import promptforge_api.db.scan_models  # noqa: F401
import promptforge_api.db.trace_models  # noqa: F401
import promptforge_api.db.user_models  # noqa: F401
from promptforge_api.config import get_settings
from promptforge_api.db.base import Base

config = context.config

# Inject the runtime DSN so the ini never holds a connection string. A caller may
# pre-set the URL on the Config (the integration tests point it at a throwaway
# container); only fall back to Settings when nothing was supplied (CLI use).
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
