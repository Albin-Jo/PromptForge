"""Integration tests for human auth (Sprint 13 / Phase 11).

Covers the DoD's login cases against the real-Postgres harness: a user logs in and gets a scoped
token, bad credentials are refused without leaking which part was wrong, refresh works and is
type-checked, expired/forged tokens are rejected, and the admin-only user-create endpoint forbids
an editor. Also pins the open-when-unconfigured posture (no ``jwt_secret`` → login is 503).

The ``auth_client`` and ``make_user`` fixtures live in conftest (shared with the authz suite).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from conftest import AUTH_SECRET
from fastapi.testclient import TestClient
from pydantic import ValidationError

from promptforge_api.config import Settings
from promptforge_api.db.user_models import User
from promptforge_api.tokens import InvalidTokenError, create_token, decode_token


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


# --- Revocable tokens via token_version (ADR 0029) -------------------------------------------


def test_bumped_token_version_invalidates_access_token(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """A previously-valid access token stops working once the user's token_version is bumped."""
    user = make_user("alice@example.com", "pw-123456")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert auth_client.get("/auth/me", headers=headers).status_code == 200  # valid before revoke

    user.token_version += 1  # revoke (what update_user / the revoke endpoint will do)

    assert auth_client.get("/auth/me", headers=headers).status_code == 401


def test_bumped_token_version_invalidates_refresh_token(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """A bumped token_version also kills an outstanding refresh token, not just the access token."""
    user = make_user("alice@example.com", "pw-123456")
    tokens = _login(auth_client, "alice@example.com", "pw-123456").json()

    user.token_version += 1

    response = auth_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 401


def test_reauth_after_revoke_issues_a_working_token(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """After a revoke, logging in again mints a token stamped at the new version — and it works."""
    user = make_user("alice@example.com", "pw-123456")
    _login(auth_client, "alice@example.com", "pw-123456")
    user.token_version += 1

    fresh = _login(auth_client, "alice@example.com", "pw-123456").json()
    response = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {fresh['access_token']}"}
    )

    assert response.status_code == 200


def test_access_token_without_version_claim_is_treated_as_zero(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """A token minted before ADR 0029 carries no 'ver' claim; it must still match a v0 user."""
    user = make_user("alice@example.com", "pw-123456")
    legacy = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=30),
        },
        AUTH_SECRET,
        algorithm="HS256",
    )

    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"})

    assert response.status_code == 200


def test_decode_token_missing_version_claim_defaults_to_zero():
    """decode_token treats an absent 'ver' claim as version 0 (backward compatibility)."""
    legacy = jwt.encode(
        {
            "sub": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "role": "editor",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=30),
        },
        AUTH_SECRET,
        algorithm="HS256",
    )

    claims = decode_token(legacy, secret=AUTH_SECRET, expected_type="access")

    assert claims.token_version == 0


def test_decode_token_rejects_a_non_integer_version_claim():
    """A malformed 'ver' claim is a broken token, not a version-0 one → InvalidTokenError."""
    bad = jwt.encode(
        {
            "sub": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "role": "editor",
            "type": "access",
            "ver": "not-an-int",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=30),
        },
        AUTH_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_token(bad, secret=AUTH_SECRET, expected_type="access")


# --- Admin user management: PATCH + revoke (Sprint 31 / ADR 0029) -----------------------------


def _admin_session(
    client: TestClient, make_user: Callable[..., User]
) -> tuple[User, dict[str, str]]:
    """Create an admin, log in, and return (the admin user, its auth header)."""
    admin = make_user("admin@example.com", "pw-123456", role="admin")
    tokens = _login(client, "admin@example.com", "pw-123456").json()
    return admin, {"Authorization": f"Bearer {tokens['access_token']}"}


def test_admin_can_change_a_user_role(auth_client: TestClient, make_user: Callable[..., User]):
    _, headers = _admin_session(auth_client, make_user)
    bob = make_user("bob@example.com", "pw-123456", role="editor")

    response = auth_client.patch(f"/auth/users/{bob.id}", headers=headers, json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_admin_can_deactivate_and_reactivate_a_user(
    auth_client: TestClient, make_user: Callable[..., User]
):
    _, headers = _admin_session(auth_client, make_user)
    bob = make_user("bob@example.com", "pw-123456", role="editor")

    off = auth_client.patch(f"/auth/users/{bob.id}", headers=headers, json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False

    on = auth_client.patch(f"/auth/users/{bob.id}", headers=headers, json={"is_active": True})
    assert on.status_code == 200 and on.json()["is_active"] is True


def test_patch_unknown_user_is_404(auth_client: TestClient, make_user: Callable[..., User]):
    _, headers = _admin_session(auth_client, make_user)

    response = auth_client.patch(
        f"/auth/users/{uuid.uuid4()}", headers=headers, json={"role": "admin"}
    )

    assert response.status_code == 404


def test_patch_empty_body_is_422(auth_client: TestClient, make_user: Callable[..., User]):
    """An empty patch is a client error, not a silent no-op."""
    _, headers = _admin_session(auth_client, make_user)
    bob = make_user("bob@example.com", "pw-123456")

    assert auth_client.patch(f"/auth/users/{bob.id}", headers=headers, json={}).status_code == 422


def test_editor_cannot_update_a_user(auth_client: TestClient, make_user: Callable[..., User]):
    make_user("ed@example.com", "pw-123456", role="editor")
    tokens = _login(auth_client, "ed@example.com", "pw-123456").json()
    bob = make_user("bob@example.com", "pw-123456")

    response = auth_client.patch(
        f"/auth/users/{bob.id}",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"role": "admin"},
    )

    assert response.status_code == 403


def test_cannot_demote_the_last_active_admin(
    auth_client: TestClient, make_user: Callable[..., User]
):
    admin, headers = _admin_session(auth_client, make_user)

    response = auth_client.patch(
        f"/auth/users/{admin.id}", headers=headers, json={"role": "editor"}
    )

    assert response.status_code == 409


def test_cannot_deactivate_the_last_active_admin(
    auth_client: TestClient, make_user: Callable[..., User]
):
    admin, headers = _admin_session(auth_client, make_user)

    response = auth_client.patch(
        f"/auth/users/{admin.id}", headers=headers, json={"is_active": False}
    )

    assert response.status_code == 409


def test_can_demote_an_admin_when_another_active_admin_remains(
    auth_client: TestClient, make_user: Callable[..., User]
):
    _, headers = _admin_session(auth_client, make_user)
    other = make_user("other-admin@example.com", "pw-123456", role="admin")

    response = auth_client.patch(
        f"/auth/users/{other.id}", headers=headers, json={"role": "editor"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "editor"


def test_role_change_revokes_the_users_outstanding_tokens(
    auth_client: TestClient, make_user: Callable[..., User]
):
    """A role change bumps token_version, so a token minted before it 401s — forcing re-auth."""
    _, headers = _admin_session(auth_client, make_user)
    bob = make_user("bob@example.com", "pw-123456", role="editor")
    bob_token = _login(auth_client, "bob@example.com", "pw-123456").json()["access_token"]
    bob_auth = {"Authorization": f"Bearer {bob_token}"}
    assert auth_client.get("/auth/me", headers=bob_auth).status_code == 200

    auth_client.patch(f"/auth/users/{bob.id}", headers=headers, json={"role": "admin"})

    assert auth_client.get("/auth/me", headers=bob_auth).status_code == 401


def test_revoke_endpoint_invalidates_tokens_but_leaves_the_account(
    auth_client: TestClient, make_user: Callable[..., User]
):
    _, headers = _admin_session(auth_client, make_user)
    bob = make_user("bob@example.com", "pw-123456", role="editor")
    bob_token = _login(auth_client, "bob@example.com", "pw-123456").json()["access_token"]
    bob_auth = {"Authorization": f"Bearer {bob_token}"}
    assert auth_client.get("/auth/me", headers=bob_auth).status_code == 200

    assert auth_client.post(f"/auth/users/{bob.id}/revoke", headers=headers).status_code == 204

    # The old token is dead, but the account is untouched — bob can simply log in again.
    assert auth_client.get("/auth/me", headers=bob_auth).status_code == 401
    assert _login(auth_client, "bob@example.com", "pw-123456").status_code == 200


def test_revoke_unknown_user_is_404(auth_client: TestClient, make_user: Callable[..., User]):
    _, headers = _admin_session(auth_client, make_user)

    response = auth_client.post(f"/auth/users/{uuid.uuid4()}/revoke", headers=headers)

    assert response.status_code == 404


def test_login_is_503_when_auth_unconfigured(client: TestClient):
    """The default conftest client has no jwt_secret: token issuance is unavailable."""
    assert _login(client, "a@example.com", "pw-123456").status_code == 503


def test_settings_reject_a_weak_jwt_secret():
    """A signing key under 32 bytes is refused at construction (HS256 minimum, RFC 7518)."""
    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short")

    # A sufficiently long secret is accepted.
    assert Settings(jwt_secret="x" * 32).jwt_secret == "x" * 32
