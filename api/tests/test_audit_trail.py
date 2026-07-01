"""Broadened audit trail (ADR 0028): each agreed action writes exactly one audit_events row.

Exercised through the full stack (router -> service -> repo -> a real throwaway Postgres). With
auth off (the ``client`` fixture) the actor is ``system``; the ``user_created`` case uses
``auth_client`` so the actor is the authenticated admin's email.
"""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.user_models import User


def _events(client: TestClient, **params: object) -> list[dict]:
    resp = client.get("/audit-log", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def _create_prompt(client: TestClient, name: str) -> None:
    resp = client.post(
        "/prompts", json={"name": name, "content": "Hi {{x}}", "input_variables": ["x"]}
    )
    assert resp.status_code == 201, resp.text


def test_prompt_create_writes_one_version_created_row(client: TestClient) -> None:
    _create_prompt(client, "greet")

    events = _events(client, action="version_created")
    assert len(events) == 1
    assert events[0]["action"] == "version_created"
    assert events[0]["target"] == "greet v1"
    assert events[0]["actor"] == "system"


def test_add_version_writes_a_second_version_created_row(client: TestClient) -> None:
    _create_prompt(client, "greet")
    resp = client.post(
        "/prompts/greet/versions", json={"content": "Hello {{x}}", "input_variables": ["x"]}
    )
    assert resp.status_code == 201, resp.text

    targets = {e["target"] for e in _events(client, action="version_created")}
    assert targets == {"greet v1", "greet v2"}


def test_non_gated_label_move_writes_label_set(client: TestClient) -> None:
    _create_prompt(client, "greet")
    resp = client.put("/prompts/greet/labels/staging", json={"version_number": 1})
    assert resp.status_code == 200, resp.text

    events = _events(client, action="label_set")
    assert len(events) == 1
    assert events[0]["target"] == "greet:staging → v1"


def test_resetting_a_label_to_the_same_version_is_not_re_audited(client: TestClient) -> None:
    """A no-op move deploys nothing, so it writes no second audit row (ADR 0028 guard)."""
    _create_prompt(client, "greet")
    body = {"version_number": 1}
    assert client.put("/prompts/greet/labels/staging", json=body).status_code == 200
    assert client.put("/prompts/greet/labels/staging", json=body).status_code == 200

    assert len(_events(client, action="label_set")) == 1


def test_golden_set_attach_and_detach_are_audited(client: TestClient) -> None:
    _create_prompt(client, "greet")
    assert (
        client.post("/datasets", json={"name": "gs", "items": [{"input": "a"}]}).status_code == 201
    )
    assert client.put("/prompts/greet/golden-set", json={"dataset": "gs"}).status_code == 200
    assert client.delete("/prompts/greet/golden-set").status_code == 200

    attached = _events(client, action="golden_set_attached")
    detached = _events(client, action="golden_set_detached")
    assert len(attached) == 1 and attached[0]["target"] == "greet ← golden-set:gs"
    assert len(detached) == 1 and detached[0]["target"] == "greet ⊘ golden-set"


def test_audit_log_pages_the_widened_set(client: TestClient) -> None:
    for name in ("a", "b", "c"):
        _create_prompt(client, name)

    page = client.get("/audit-log", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3  # three version_created rows
    assert len(page["events"]) == 2  # paged to the first two, newest first


def test_user_create_is_audited_with_the_admins_email(
    auth_client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    make_user("admin@example.com", "pw-123456", role="admin")
    token = auth_client.post(
        "/auth/login", json={"email": "admin@example.com", "password": "pw-123456"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = auth_client.post(
        "/auth/users",
        json={"email": "New@Example.com", "password": "pw-abcdef", "role": "editor"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    resp = auth_client.get("/audit-log", params={"action": "user_created"}, headers=headers)
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["actor"] == "admin@example.com"
    assert events[0]["target"] == "user:new@example.com (editor)"
