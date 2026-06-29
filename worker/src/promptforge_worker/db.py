"""Database access for worker tasks — a context-managed session over the API's engine.

Sprint 8: the worker now runs real evals, which read runs/datasets/versions and write
scores, so it needs a unit-of-work outside FastAPI. We reuse the API's engine and
session factory (``promptforge_api.db.engine``) rather than building a second one — one
connection-pool config, one place that reads ``PROMPTFORGE_DATABASE_URL`` (ADR 0011).
The worker process just needs that env var set (the compose worker block injects it).

The API's own ``get_session`` is a FastAPI *generator dependency* (it ``yield``s into the
request lifecycle); a Celery task isn't a request, so it can't use it. :func:`session_scope`
is the same commit-on-success / rollback-on-error contract as an explicit context manager a
task can ``with``-open around its unit of work.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from promptforge_api.db.engine import SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a task-scoped session; commit if the block returns, roll back on any error.

    Mirrors ``promptforge_api.db.engine.get_session`` but as a context manager usable
    outside FastAPI. The task does its reads + writes inside the ``with`` block; leaving
    it cleanly commits the whole unit of work, and any exception rolls it all back so a
    crashed eval never leaves a half-written run behind (it'll be retried — the task is
    idempotent on its run id).
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
