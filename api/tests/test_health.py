"""Smoke tests for the liveness endpoint and correlation-id propagation."""

from fastapi.testclient import TestClient

from promptforge_api.main import create_app

client = TestClient(create_app())


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_mints_request_id_when_absent() -> None:
    response = client.get("/healthz")
    assert response.headers["X-Request-ID"]


def test_healthz_echoes_provided_request_id() -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "test-123"})
    assert response.headers["X-Request-ID"] == "test-123"
