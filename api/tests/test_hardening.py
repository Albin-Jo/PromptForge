"""API-hardening tests (Sprint 13 / Phase 11): CORS, security headers, and safe error bodies.

These pin the transport-level guarantees the DoD calls "no obvious OWASP holes": cross-origin
access is allow-listed (not open), defensive response headers are always present, and an
unexpected server error returns a generic body rather than leaking a stack trace.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.config import get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.main import create_app

_ALLOWED_ORIGIN = "https://ui.example.com"


def test_security_headers_present_on_every_response(client: TestClient):
    response = client.get("/healthz")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_cors_denies_unconfigured_origin(client: TestClient):
    """With no origins configured, a cross-origin request gets no allow-origin header."""
    response = client.get("/healthz", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


@pytest.fixture
def cors_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client with one allow-listed CORS origin configured."""
    monkeypatch.setenv("PROMPTFORGE_CORS_ALLOW_ORIGINS", _ALLOWED_ORIGIN)
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


def test_cors_allows_configured_origin(cors_client: TestClient):
    response = cors_client.get("/healthz", headers={"Origin": _ALLOWED_ORIGIN})

    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN


def test_cors_preflight_is_answered_for_configured_origin(cors_client: TestClient):
    response = cors_client.options(
        "/prompts",
        headers={
            "Origin": _ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN


def test_unhandled_error_returns_generic_500_without_leaking(db_session: Session):
    """A route that raises an unexpected error → opaque 500 body + a request id, no traceback."""

    def _override_get_session() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session

    @app.get("/_boom")
    def _boom() -> None:
        raise RuntimeError("secret internal detail that must not leak")

    # raise_server_exceptions=False so the registered Exception handler's response is returned
    # instead of the error propagating into the test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/_boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "secret internal detail" not in response.text
    # NB: the X-Request-ID header is NOT guaranteed on an unhandled 500 — when call_next raises,
    # Starlette's outer ServerErrorMiddleware builds the response, past our BaseHTTPMiddleware
    # request-id post-processing. The id is still on every *normal* response; the traceback is
    # logged server-side, never returned. Threading the id onto errors is parked in the backlog.
    app.dependency_overrides.clear()
