"""Contract tests: the real SDK client driving the real API end-to-end.

These pin the SDK<->API agreement so the two can't drift: a change to a route, a status
code, or the render response shape that breaks the SDK fails here. They run against the
real app and a real throwaway Postgres (the ``db_session`` fixture), so they need Docker.

Mechanics: the SDK uses a *sync* ``httpx.Client``, which can't drive an async
``ASGITransport``. So we hand the SDK a ``MockTransport`` whose handler forwards each
request into Starlette's ``TestClient`` (which runs the real app) and returns its real
response — a genuine round-trip through router -> service -> repository -> DB, driven
synchronously.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge import PromptForgeAPIError, PromptForgeClient, PromptNotFoundError
from promptforge_api.config import get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.main import create_app


def _bind_session(app: FastAPI, db_session: Session) -> None:
    """Make the app share the test's rolled-back transaction (as the client fixture does)."""

    def _override_get_session() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_session] = _override_get_session


def _sdk_over(seed: TestClient, **kwargs: object) -> PromptForgeClient:
    """An SDK client whose requests are served by the real app behind *seed*."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = seed.request(
            request.method,
            str(request.url),
            content=request.content,
            headers=request.headers,
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    return PromptForgeClient("http://testserver", transport=httpx.MockTransport(handler), **kwargs)


SeedAndSdk = Callable[..., tuple[TestClient, PromptForgeClient]]


@pytest.fixture
def seed_and_sdk(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[SeedAndSdk]:
    """Factory: build the app (optionally with api_keys) and a seeder + SDK over it."""
    apps: list[FastAPI] = []

    def _make(
        *, api_keys: str | None = None, **sdk_kwargs: object
    ) -> tuple[TestClient, PromptForgeClient]:
        if api_keys is not None:
            monkeypatch.setenv("PROMPTFORGE_API_KEYS", api_keys)
        get_settings.cache_clear()  # re-read env (monkeypatch reverts it on teardown)
        app = create_app()
        apps.append(app)
        _bind_session(app, db_session)
        seed = TestClient(app)
        return seed, _sdk_over(seed, **sdk_kwargs)

    yield _make

    get_settings.cache_clear()
    for app in apps:
        app.dependency_overrides.clear()


def _create_and_label(seed: TestClient, **overrides: object) -> None:
    payload: dict = {
        "name": "contract",
        "content": "Hello {{name}}",
        "input_variables": ["name"],
    }
    payload.update(overrides)
    assert seed.post("/prompts", json=payload).status_code == 201
    label_url = f"/prompts/{payload['name']}/labels/staging"
    assert seed.put(label_url, json={"version_number": 1}).status_code == 200


def test_sdk_renders_through_the_real_api(seed_and_sdk) -> None:
    seed, sdk = seed_and_sdk()
    _create_and_label(seed)

    result = sdk.get_prompt("contract", label="staging", variables={"name": "Ada"})
    assert result.prompt == "Hello Ada"


def test_sdk_floating_fetch_follows_a_deploy(seed_and_sdk) -> None:
    seed, sdk = seed_and_sdk(cache_ttl=0)  # disable SDK cache so each call re-fetches
    _create_and_label(seed)
    assert sdk.get_prompt("contract", label="staging", variables={"name": "x"}).prompt == "Hello x"

    seed.post(
        "/prompts/contract/versions",
        json={"content": "Hi {{name}}", "input_variables": ["name"]},
    )
    seed.put("/prompts/contract/labels/staging", json={"version_number": 2})
    assert sdk.get_prompt("contract", label="staging", variables={"name": "x"}).prompt == "Hi x"


def test_sdk_raises_not_found_for_missing_prompt(seed_and_sdk) -> None:
    seed, sdk = seed_and_sdk()
    with pytest.raises(PromptNotFoundError):
        sdk.get_prompt("does-not-exist")


def test_protected_endpoint_rejects_sdk_without_key(seed_and_sdk) -> None:
    seed, sdk = seed_and_sdk(api_keys="s3cret")  # SDK built with no api_key
    _create_and_label(seed)
    with pytest.raises(PromptForgeAPIError) as info:
        sdk.get_prompt("contract", label="staging", variables={"name": "x"})
    assert info.value.status_code == 401


def test_protected_endpoint_accepts_sdk_with_key(seed_and_sdk: SeedAndSdk) -> None:
    seed, sdk = seed_and_sdk(api_keys="s3cret", api_key="s3cret")
    _create_and_label(seed)
    assert sdk.get_prompt("contract", label="staging", variables={"name": "x"}).prompt == "Hello x"
