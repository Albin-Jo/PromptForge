"""Tests for ``GET /models`` (Sprint 28): the read-only model list the playground picker uses.

The endpoint just echoes ``settings.gateway_models``, so we override the ``get_settings``
dependency rather than touching the environment or a database — no DB is needed.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from promptforge_api.config import Settings, get_settings
from promptforge_api.main import create_app


@pytest.fixture
def client_with_models() -> Iterator[tuple[TestClient, list[str]]]:
    """A client whose ``GET /models`` reflects whatever list the test pins via ``set_models``."""
    models: list[str] = []
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(gateway_models=models)
    with TestClient(app) as test_client:
        yield test_client, models
    app.dependency_overrides.clear()


def test_models_returns_configured_list(client_with_models: tuple[TestClient, list[str]]) -> None:
    client, models = client_with_models
    models[:] = ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6"]

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6"]}


def test_models_returns_empty_list_when_unconfigured(
    client_with_models: tuple[TestClient, list[str]],
) -> None:
    client, _models = client_with_models

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == {"models": []}
