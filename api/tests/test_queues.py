"""Queue/worker health (Sprint 29 T3): the read degrades without a live broker.

The service is a pure mapping over an injected inspector, so the unit tests hand it a fake snapshot
or make it raise — no Redis/Celery needed. The HTTP tests override the inspector dependency and
confirm the shape plus that the endpoint is admin-gated.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from promptforge_api.db.user_models import User
from promptforge_api.services.queues import (
    QueueDepth,
    QueueProbeError,
    RawQueueSnapshot,
    get_queue_inspector,
    read_queue_health,
)


class _FakeInspector:
    """A QueueInspector double: returns a snapshot, or raises to mimic a dead broker."""

    def __init__(self, *, snapshot: RawQueueSnapshot | None = None, fail: bool = False) -> None:
        self._snapshot = snapshot
        self._fail = fail

    def snapshot(self) -> RawQueueSnapshot:
        if self._fail:
            raise QueueProbeError("broker unreachable")
        assert self._snapshot is not None
        return self._snapshot


_HEALTHY = RawQueueSnapshot(
    queues=[
        QueueDepth("celery", 0),
        QueueDepth("evals", 2),
        QueueDepth("scans", 1),
        QueueDepth("traces", 0),
    ],
    worker_count=1,
    active_count=3,
)


def _token(client: TestClient, make_user: Callable[..., User], email: str, role: str) -> str:
    make_user(email, "pw-123456", role=role)
    tokens = client.post("/auth/login", json={"email": email, "password": "pw-123456"}).json()
    return tokens["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- service (pure mapping)
def test_read_queue_health_maps_a_healthy_snapshot() -> None:
    health = read_queue_health(_FakeInspector(snapshot=_HEALTHY))

    assert health.available is True
    assert health.workers == 1
    assert health.active == 3
    assert health.queued == 3  # sum of the per-queue depths
    assert health.queues == _HEALTHY.queues


def test_read_queue_health_degrades_when_broker_unreachable() -> None:
    health = read_queue_health(_FakeInspector(fail=True))

    assert health.available is False
    assert health.workers is None
    assert health.active is None
    assert health.queued is None
    assert health.queues is None


# --------------------------------------------------------------------- HTTP surface
def test_queue_health_endpoint_returns_shape(client: TestClient) -> None:
    client.app.dependency_overrides[get_queue_inspector] = lambda: _FakeInspector(snapshot=_HEALTHY)

    body = client.get("/admin/queues").json()

    assert body["available"] is True
    assert body["workers"] == 1
    assert body["active"] == 3
    assert body["queued"] == 3
    assert body["queues"] == [
        {"name": "celery", "depth": 0},
        {"name": "evals", "depth": 2},
        {"name": "scans", "depth": 1},
        {"name": "traces", "depth": 0},
    ]


def test_queue_health_endpoint_reports_unavailable_without_a_broker(client: TestClient) -> None:
    client.app.dependency_overrides[get_queue_inspector] = lambda: _FakeInspector(fail=True)

    body = client.get("/admin/queues").json()

    assert body == {
        "available": False,
        "workers": None,
        "active": None,
        "queued": None,
        "queues": None,
    }


def test_queue_health_requires_a_token_when_auth_on(auth_client: TestClient) -> None:
    # Override the inspector so we're exercising the gate, not a real broker.
    auth_client.app.dependency_overrides[get_queue_inspector] = lambda: _FakeInspector(
        snapshot=_HEALTHY
    )
    assert auth_client.get("/admin/queues").status_code == 401


def test_queue_health_is_forbidden_for_an_editor(
    auth_client: TestClient, make_user: Callable[..., User]
) -> None:
    auth_client.app.dependency_overrides[get_queue_inspector] = lambda: _FakeInspector(
        snapshot=_HEALTHY
    )
    editor = _token(auth_client, make_user, "ed@example.com", "editor")
    assert auth_client.get("/admin/queues", headers=_headers(editor)).status_code == 403
