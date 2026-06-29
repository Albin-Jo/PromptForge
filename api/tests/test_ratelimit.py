"""Rate-limiting + request-size tests (Sprint 13 / Phase 11).

The DoD's "abusive rates throttled" case. Throttling is proven deterministically with the in-memory
limiter injected via the factory (no Redis container needed); fail-open is unit-tested directly on
the Redis adapter; ``/health`` is shown to stay exempt; and the request-size guard returns 413.
"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from conftest import AUTH_SECRET
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from promptforge_api import ratelimit
from promptforge_api.config import get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.main import create_app
from promptforge_api.middleware import _principal_key
from promptforge_api.ratelimit import InMemoryRateLimiter, RedisRateLimiter
from promptforge_api.tokens import create_token


def _fake_request(headers: dict[str, str] | None = None, client_host: str | None = "1.2.3.4"):
    """A minimal stand-in for a Starlette Request for _principal_key (case-insensitive headers)."""
    return SimpleNamespace(
        headers=Headers(headers or {}),
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


def test_principal_key_prefers_api_key():
    request = _fake_request({"X-API-Key": "abcdef123456"})
    assert _principal_key(request, jwt_secret=None, trust_forwarded=False) == "api-key:abcdef12"


def test_principal_key_uses_user_from_bearer_token():
    user_id = uuid.uuid4()
    token = create_token(
        subject=user_id, role="editor", token_type="access", secret=AUTH_SECRET, ttl_seconds=60
    )
    request = _fake_request({"Authorization": f"Bearer {token}"})
    assert (
        _principal_key(request, jwt_secret=AUTH_SECRET, trust_forwarded=False) == f"user:{user_id}"
    )


def test_principal_key_falls_back_to_ip_for_invalid_token():
    request = _fake_request({"Authorization": "Bearer not-a-real-token"})
    assert _principal_key(request, jwt_secret=AUTH_SECRET, trust_forwarded=False) == "ip:1.2.3.4"


def test_principal_key_ignores_forwarded_header_by_default():
    request = _fake_request({"X-Forwarded-For": "9.9.9.9, 10.0.0.1"})
    assert _principal_key(request, jwt_secret=None, trust_forwarded=False) == "ip:1.2.3.4"


def test_principal_key_honors_forwarded_header_when_trusted():
    request = _fake_request({"X-Forwarded-For": "9.9.9.9, 10.0.0.1"})
    assert _principal_key(request, jwt_secret=None, trust_forwarded=True) == "ip:9.9.9.9"


class _FakeRedis:
    """A tiny in-process stand-in for the bits of redis RedisRateLimiter uses."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


def test_redis_limiter_allows_then_blocks_with_retry_after():
    """Exercise the real INCR/EXPIRE/limit logic against a fake client (no live Redis)."""
    limiter = RedisRateLimiter("redis://unused", limit=2, window_seconds=60, client=_FakeRedis())

    assert limiter.hit("api-key:abc").allowed is True
    assert limiter.hit("api-key:abc").allowed is True
    blocked = limiter.hit("api-key:abc")
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 60
    # A different principal has its own counter.
    assert limiter.hit("ip:9.9.9.9").allowed is True


def test_requests_are_throttled_after_the_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    limiter = InMemoryRateLimiter(limit=3, window_seconds=60)
    monkeypatch.setattr(ratelimit, "get_rate_limiter", lambda: limiter)

    # Three requests are within the limit, the fourth trips it.
    statuses = [client.get("/blocks").status_code for _ in range(4)]

    assert statuses[:3] == [200, 200, 200]
    response = client.get("/blocks")
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_health_is_never_throttled(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    # A limiter that denies everything (limit 0): /health must still answer, /blocks must not.
    deny_all = InMemoryRateLimiter(limit=0, window_seconds=60)
    monkeypatch.setattr(ratelimit, "get_rate_limiter", lambda: deny_all)

    assert client.get("/healthz").status_code == 200
    assert client.get("/blocks").status_code == 429


def test_redis_limiter_fails_open_when_redis_is_unreachable():
    """A limiter outage must never block a request: an unreachable Redis → allowed."""
    limiter = RedisRateLimiter(
        "redis://localhost:6390/0",  # nothing listening here
        limit=1,
        window_seconds=60,
        timeout_seconds=0.1,
    )

    decision = limiter.hit("ip:1.2.3.4")

    assert decision.allowed is True


@pytest.fixture
def tiny_body_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose max request body is 10 bytes, to exercise the 413 guard."""
    monkeypatch.setenv("PROMPTFORGE_MAX_REQUEST_BYTES", "10")
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


def test_oversized_request_body_is_rejected(tiny_body_client: TestClient):
    response = tiny_body_client.post(
        "/prompts", json={"name": "greeter", "content": "this body is well over ten bytes"}
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}
