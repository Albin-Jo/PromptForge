"""Authorization tests (Sprint 13 / Phase 11): who may author vs. who may promote.

The DoD's authz "forbidden" case lives here. The role split (ADR 0018 / Task 3):

* **editor or admin** may author — create prompts/versions, blocks, datasets, attach golden sets,
  trigger evals/scans;
* **admin only** may promote (move a label = deploy);
* with no ``jwt_secret`` configured the gate is a no-op, so the existing SDK/registry behaviour and
  the rest of the suite keep working without tokens.
"""

from collections.abc import Callable

from fastapi.testclient import TestClient

from promptforge_api.db.user_models import User

_PROMPT = {"name": "greeter", "content": "Hello there"}


def _token(client: TestClient, make_user: Callable[..., User], email: str, role: str) -> str:
    make_user(email, "pw-123456", role=role)
    tokens = client.post("/auth/login", json={"email": email, "password": "pw-123456"}).json()
    return tokens["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_editor_can_create_prompt(auth_client: TestClient, make_user: Callable[..., User]):
    token = _token(auth_client, make_user, "ed@example.com", "editor")

    response = auth_client.post("/prompts", json=_PROMPT, headers=_headers(token))

    assert response.status_code == 201


def test_creating_a_prompt_without_a_token_is_401(auth_client: TestClient):
    """Auth is on (secret configured) but no token presented → 401, not a silent create."""
    assert auth_client.post("/prompts", json=_PROMPT).status_code == 401


def test_editor_is_forbidden_from_promoting(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """The DoD 'forbidden' case: an editor may author but not deploy."""
    editor = _token(auth_client, make_user, "ed@example.com", "editor")
    auth_client.post("/prompts", json=_PROMPT, headers=_headers(editor))

    response = auth_client.put(
        "/prompts/greeter/labels/staging",
        json={"version_number": 1},
        headers=_headers(editor),
    )

    assert response.status_code == 403


def test_admin_can_promote(auth_client: TestClient, make_user: Callable[..., User]):
    """An admin clears the authz gate; 'staging' is not the gated label, so it moves freely."""
    editor = _token(auth_client, make_user, "ed@example.com", "editor")
    auth_client.post("/prompts", json=_PROMPT, headers=_headers(editor))
    admin = _token(auth_client, make_user, "admin@example.com", "admin")

    response = auth_client.put(
        "/prompts/greeter/labels/staging",
        json={"version_number": 1},
        headers=_headers(admin),
    )

    assert response.status_code == 200


def test_registry_is_open_when_auth_is_unconfigured(client: TestClient):
    """No jwt_secret (the default fixture): the gate is a no-op, so a create needs no token.

    This pins that adding auth did not break the existing token-free registry/SDK behaviour.
    """
    assert client.post("/prompts", json=_PROMPT).status_code == 201


def test_sdk_render_path_needs_no_user_token_even_with_auth_on(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """The SDK fetch (render-by-label) is gated by X-API-Key, not the JWT editor gate.

    Pins ADR-0018's two-path claim: with user auth enabled, the machine/SDK path still works with
    no bearer token (API keys are unset here, so that gate is open).
    """
    admin = _token(auth_client, make_user, "admin@example.com", "admin")
    auth_client.post("/prompts", json=_PROMPT, headers=_headers(admin))
    auth_client.put(
        "/prompts/greeter/labels/staging", json={"version_number": 1}, headers=_headers(admin)
    )

    # No Authorization header at all — the SDK render path must still resolve the label.
    response = auth_client.post(
        "/prompts/greeter/render", json={"label": "staging", "variables": {}}
    )

    assert response.status_code == 200
    assert response.json()["prompt"] == "Hello there"
