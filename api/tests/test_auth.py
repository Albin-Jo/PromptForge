"""Integration tests for human auth (Sprint 13 / Phase 11).

Covers the DoD's login cases against the real-Postgres harness: a user logs in and gets a scoped
token, bad credentials are refused without leaking which part was wrong, refresh works and is
type-checked, expired/forged tokens are rejected, and the admin-only user-create endpoint forbids
an editor. Also pins the open-when-unconfigured posture (no ``jwt_secret`` → login is 503).

The ``auth_client`` and ``make_user`` fixtures live in conftest (shared with the authz suite).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from conftest import AUTH_SECRET
from fastapi.testclient import TestClient
from pydantic import ValidationError

from promptforge_api.config import Settings
from promptforge_api.db.user_models import User
from promptforge_api.tokens import create_token


def _login(client: TestClient, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_returns_access_and_refresh_tokens(
    auth_client: TestClient, make_user: Callable[..., User]
):
    make_user("alice@example.com", "correct horse battery")

    response = _login(auth_client, "alice@example.com", "correct horse battery")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


def test_login_is_case_insensitive_on_email(
    auth_client: TestClient, make_user: Callable[..., User]
):
    make_user("alice@example.com", "pw-123456")

    assert _login(auth_client, "ALICE@example.com", "pw-123456").status_code == 200


def test_login_wrong_password_is_401(auth_client: TestClient, make_user: Callable[..., User]):
    make_user("alice@example.com", "pw-123456")

    assert _login(auth_client, "alice@example.com", "wrong").status_code == 401


def test_login_unknown_email_is_401(auth_client: TestClient):
    assert _login(auth_client, "nobody@example.com", "whatever").status_code == 401


def test_login_disabled_user_is_401(auth_client: TestClient, make_user: Callable[..., User]):
    user = make_user("alice@example.com", "pw-123456")
    user.is_active = False

    assert _login(auth_client, "alice@example.com", "pw-123456").status_code == 401


def test_me_returns_current_user(auth_client: TestClient, make_user: Callable[..., User]):
    make_user("alice@example.com", "pw-123456", role="admin")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()

    response = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "admin"
    assert "password_hash" not in body


def test_me_without_token_is_401(auth_client: TestClient):
    assert auth_client.get("/auth/me").status_code == 401


def test_refresh_returns_a_new_access_token(
    auth_client: TestClient, make_user: Callable[..., User]
):
    make_user("alice@example.com", "pw-123456")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()

    response = auth_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert "refresh_token" not in body  # refresh returns only a new access token


def test_refresh_rejects_an_access_token(auth_client: TestClient, make_user: Callable[..., User]):
    """An access token presented to /auth/refresh is the wrong type → 401."""
    make_user("alice@example.com", "pw-123456")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()

    response = auth_client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})

    assert response.status_code == 401


def test_expired_access_token_is_rejected(auth_client: TestClient, make_user: Callable[..., User]):
    user = make_user("alice@example.com", "pw-123456")
    expired = create_token(
        subject=user.id,
        role=user.role,
        token_type="access",
        secret=AUTH_SECRET,
        ttl_seconds=-10,  # already expired
        now=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected(
    auth_client: TestClient, make_user: Callable[..., User]
):
    user = make_user("alice@example.com", "pw-123456")
    forged = create_token(
        subject=user.id,
        role=user.role,
        token_type="access",
        secret="a-different-secret-of-at-least-32-bytes-long",
        ttl_seconds=1800,
    )

    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def _admin_headers(client: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    make_user("admin@example.com", "pw-123456", role="admin")
    tokens = _login(client, "admin@example.com", "pw-123456").json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_admin_can_create_user(auth_client: TestClient, make_user: Callable[..., User]):
    response = auth_client.post(
        "/auth/users",
        headers=_admin_headers(auth_client, make_user),
        json={"email": "newbie@example.com", "password": "pw-12345678", "role": "editor"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newbie@example.com"
    assert body["role"] == "editor"


def test_editor_cannot_create_user(auth_client: TestClient, make_user: Callable[..., User]):
    make_user("ed@example.com", "pw-123456", role="editor")
    tokens = _login(auth_client, "ed@example.com", "pw-123456").json()

    response = auth_client.post(
        "/auth/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"email": "newbie@example.com", "password": "pw-12345678", "role": "editor"},
    )

    assert response.status_code == 403


def test_create_user_without_token_is_401(auth_client: TestClient):
    response = auth_client.post(
        "/auth/users", json={"email": "x@example.com", "password": "pw-12345678", "role": "editor"}
    )

    assert response.status_code == 401


def test_create_user_duplicate_email_is_409(
    auth_client: TestClient, make_user: Callable[..., User]
):
    headers = _admin_headers(auth_client, make_user)
    make_user("taken@example.com", "pw-123456")

    response = auth_client.post(
        "/auth/users",
        headers=headers,
        json={"email": "taken@example.com", "password": "pw-12345678", "role": "editor"},
    )

    assert response.status_code == 409


def test_admin_can_list_users(auth_client: TestClient, make_user: Callable[..., User]):
    headers = _admin_headers(auth_client, make_user)
    make_user("ed@example.com", "pw-123456", role="editor")

    response = auth_client.get("/auth/users", headers=headers)

    assert response.status_code == 200
    by_email = {u["email"]: u for u in response.json()}
    assert by_email["admin@example.com"]["role"] == "admin"
    assert by_email["ed@example.com"]["role"] == "editor"
    # UserRead never leaks the password hash.
    assert "password_hash" not in by_email["ed@example.com"]


def test_editor_cannot_list_users(auth_client: TestClient, make_user: Callable[..., User]):
    make_user("ed@example.com", "pw-123456", role="editor")
    tokens = _login(auth_client, "ed@example.com", "pw-123456").json()

    response = auth_client.get(
        "/auth/users", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 403


def test_list_users_without_token_is_401(auth_client: TestClient):
    assert auth_client.get("/auth/users").status_code == 401


def test_refresh_is_rejected_for_a_disabled_user(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """Deactivating a user takes effect on their next refresh even though tokens are stateless."""
    user = make_user("alice@example.com", "pw-123456")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()
    user.is_active = False

    response = auth_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 401


def test_login_is_503_when_auth_unconfigured(client: TestClient):
    """The default conftest client has no jwt_secret: token issuance is unavailable."""
    assert _login(client, "a@example.com", "pw-123456").status_code == 503


def test_settings_reject_a_weak_jwt_secret():
    """A signing key under 32 bytes is refused at construction (HS256 minimum, RFC 7518)."""
    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short")

    # A sufficiently long secret is accepted.
    assert Settings(jwt_secret="x" * 32).jwt_secret == "x" * 32
