"""Shared fixtures for worker tests.

Most task tests run in-process with an in-memory idempotency store (no broker, no
Redis) — fast and deterministic. The one *real-broker* test (idempotency through an
actual worker) needs a live Redis, which we get from a throwaway Testcontainer here,
mirroring the API's integration-test setup.
"""

import os

# Disable the Ryuk reaper sidecar before importing testcontainers — its port mapping
# races on Docker Desktop / Windows. The `with RedisContainer(...)` block still tears
# the container down on session teardown. (Same rationale as the API conftest.)
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# The worker reuses the API's Alembic config to build the schema (ADR 0011: one migration set,
# owned by the API package). Two levels up from worker/tests/ is the repo root.
_API_DIR = Path(__file__).resolve().parents[2] / "api"
_ALEMBIC_INI = _API_DIR / "alembic.ini"


@pytest.fixture(scope="session")
def redis_base_url() -> Iterator[str]:
    """Start one throwaway Redis for the session; yield its ``redis://host:port`` base."""
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}"


@pytest.fixture(scope="session")
def worker_db_url() -> Iterator[str]:
    """Start one throwaway Postgres for the session; yield a psycopg (v3) DSN.

    The eval task talks to a real database (it loads runs/datasets/versions and writes scores),
    so the full-run integration test needs a real Postgres — mocks would prove nothing about the
    SQL, the FKs, or the migration. Separate from the API suite's container; both are throwaway.
    """
    with PostgresContainer(
        "postgres:17", username="promptforge", password="promptforge", dbname="promptforge"
    ) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        yield f"postgresql+psycopg://promptforge:promptforge@{host}:{port}/promptforge"


@pytest.fixture(scope="session")
def worker_engine(worker_db_url: str) -> Iterator[Engine]:
    """Build the schema by running the real migrations (``upgrade head``), then yield the engine."""
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", worker_db_url)
    command.upgrade(config, "head")
    eng = create_engine(worker_db_url)
    yield eng
    eng.dispose()
