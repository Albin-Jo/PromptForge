"""Shared fixtures for API integration tests.

These tests run against a **real, throwaway Postgres** (Testcontainers) rather
than mocks — the only way to catch SQL, constraint, and migration bugs. Two ideas
do the heavy lifting:

1. **Migrate, don't ``create_all``.** The schema is built by running our actual
   Alembic migration (``upgrade head``). If a migration ever drifts from the
   models, these tests fail — which is the point.

2. **One transaction per test, rolled back at the end.** This is an *isolation*
   technique (the "I" in ACID). Each test opens a database transaction; the app's
   own commits run as SAVEPOINTs *inside* it (``join_transaction_mode=
   "create_savepoint"``), so a request still sees its own writes — but when the
   test finishes we ``ROLLBACK`` the outer transaction and every change vanishes.
   Tests stay fast (no re-truncating tables) and never leak state into each other.
"""

import os

# Disable the Ryuk resource-reaper sidecar before importing testcontainers: its
# port mapping races on Docker Desktop / Windows and intermittently fails
# container startup. Our fixtures use ``with PostgresContainer(...)``, so the
# Postgres container is still torn down on session teardown.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from promptforge_api import enqueue
from promptforge_api.config import get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.db.user_models import User
from promptforge_api.main import create_app
from promptforge_api.security import hash_password

# A signing secret for the auth-enabled fixtures. >= 32 bytes so PyJWT doesn't warn about a weak
# HMAC key; tests that mint their own tokens import this so they sign with the same key.
AUTH_SECRET = "test-secret-please-change-0123456789abcdef"

_API_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _API_DIR / "alembic.ini"


@pytest.fixture(autouse=True)
def captured_enqueues(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Neutralise real Celery enqueues in API tests, and record what *would* have been sent.

    Saving a version triggers a security scan (unconditionally) and, with a golden set, a gating
    eval — both via ``enqueue.submit_*``, which would otherwise publish to a real broker the test
    suite doesn't run. Autouse so plain CRUD tests stay broker-free; the recorder it yields lets a
    test assert what was enqueued (e.g. that scan-on-save actually fired). Tests that build their
    own services with their own recorders (the promotion-gate suite) are unaffected — they don't
    call these module functions.
    """
    captured = SimpleNamespace(scans=[], evals=[])
    monkeypatch.setattr(enqueue, "submit_scan", captured.scans.append)
    monkeypatch.setattr(enqueue, "submit_eval", captured.evals.append)
    return captured


@pytest.fixture(scope="session")
def _postgres() -> Iterator[PostgresContainer]:
    """Start one Postgres container for the whole test session."""
    with PostgresContainer(
        "postgres:17", username="promptforge", password="promptforge", dbname="promptforge"
    ) as container:
        yield container


@pytest.fixture(scope="session")
def db_url(_postgres: PostgresContainer) -> str:
    """A psycopg (v3) DSN for the running container."""
    host = _postgres.get_container_host_ip()
    port = _postgres.get_exposed_port(5432)
    return f"postgresql+psycopg://promptforge:promptforge@{host}:{port}/promptforge"


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    """Build the schema by running real migrations, then hand back the engine."""
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(config, "head")

    eng = create_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session wrapped in an outer transaction that is rolled back per test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose requests use the per-test transactional session.

    Overriding ``get_session`` makes the app share the test's transaction, so the
    rollback in ``db_session`` undoes anything the endpoints wrote.
    """

    def _override_get_session() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    """Insert a user directly so auth/authz tests have something to authenticate against."""

    def _make(email: str, password: str, role: str = "editor") -> User:
        user = User(email=email.lower(), password_hash=hash_password(password), role=role)
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture
def auth_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient with user auth *enabled* (a signing secret configured).

    Mirrors :func:`client` but sets ``PROMPTFORGE_JWT_SECRET`` and clears the settings cache so the
    request-time ``get_settings()`` dependency sees it — used by the auth + authz suites.
    """
    monkeypatch.setenv("PROMPTFORGE_JWT_SECRET", AUTH_SECRET)
    get_settings.cache_clear()

    def _override_get_session() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
