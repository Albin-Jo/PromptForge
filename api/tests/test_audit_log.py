"""Integration tests for GET /audit-log (Sprint 25).

The endpoint maps the promotion_audits table to AuditEvent responses.
Three cases: admin sees the log, editor is 403, no token is 401.
Data-carrying test creates a real prompt + promotion audit row to verify
the response shape.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.user_models import User

# Reuse the auth helper from the authz test module.
_AUTH_SECRET = "test-secret-please-change-0123456789abcdef"


def _token(client: TestClient, make_user: Callable[..., User], email: str, role: str) -> str:
    make_user(email, "pw-123456", role=role)
    tokens = client.post("/auth/login", json={"email": email, "password": "pw-123456"}).json()
    return tokens["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_audit_log_requires_admin_returns_403_for_editor(
    auth_client: TestClient, make_user: Callable[..., User]
) -> None:
    editor = _token(auth_client, make_user, "ed@example.com", "editor")
    assert auth_client.get("/audit-log", headers=_headers(editor)).status_code == 403


def test_audit_log_requires_auth_returns_401_without_token(auth_client: TestClient) -> None:
    assert auth_client.get("/audit-log").status_code == 401


def test_audit_log_returns_empty_page_when_no_events(
    auth_client: TestClient, make_user: Callable[..., User]
) -> None:
    admin = _token(auth_client, make_user, "adm@example.com", "admin")
    response = auth_client.get("/audit-log", headers=_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["events"] == []
    assert body["total"] == 0


def test_audit_log_lists_promotion_events(
    auth_client: TestClient,
    make_user: Callable[..., User],
    db_session: Session,
) -> None:
    """End-to-end: promote a prompt → audit row is visible in /audit-log."""
    from promptforge_api.db.models import Prompt
    from promptforge_api.db.promotion_models import PromotionAudit

    admin = _token(auth_client, make_user, "adm2@example.com", "admin")

    # Seed a prompt and a promotion audit row directly (bypasses gate logic).
    prompt = Prompt(name="test-prompt")
    db_session.add(prompt)
    db_session.flush()

    audit_row = PromotionAudit(
        prompt_id=prompt.id,
        label="production",
        to_version_number=1,
        decision="promoted",
        reason="all gates passed",
        actor="adm2@example.com",
    )
    db_session.add(audit_row)
    db_session.flush()

    response = auth_client.get("/audit-log", headers=_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    event = body["events"][0]
    assert event["actor"] == "adm2@example.com"
    assert event["action"] == "promoted"
    assert "test-prompt" in event["target"]
    assert "production" in event["target"]
    assert "v1" in event["target"]
