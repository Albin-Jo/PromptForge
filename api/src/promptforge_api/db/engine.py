"""Database engine and session factory — synchronous (ADR 0003).

``create_engine`` does not open a connection; the pool connects lazily on first
use, so importing this module is safe even when Postgres is down. ``get_session``
is the FastAPI dependency that hands a route a unit-of-work: it commits if the
handler returns cleanly and rolls back on any exception, so a half-finished
request never leaves a partial write behind.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from promptforge_api.config import get_settings

# pool_pre_ping issues a tiny liveness check on checkout so a connection dropped
# by Postgres (idle timeout, restart) is transparently replaced instead of
# surfacing as a mid-request error.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)

# expire_on_commit=False keeps attributes readable after commit; the service
# layer converts ORM objects to DTOs while the session is live, so routes never
# touch a detached instance regardless.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session; commit on success, roll back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
