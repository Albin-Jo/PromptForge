"""Unit tests for the webhook delivery task (Sprint 11).

Run the task body in-process with a fake HTTP client (no network, no broker): assert it POSTs
the exact payload, signs it when a secret is set, and classifies receiver responses correctly —
5xx / network errors are transient (retry), 4xx is a permanent reject (give up).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from promptforge_worker.errors import TransientWebhookError
from promptforge_worker.tasks import deliver_webhook


class _FakeResponse:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def _lower_headers(request: urllib.request.Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.header_items()}


def test_delivers_and_signs_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["headers"] = _lower_headers(request)
        return _FakeResponse(200)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    payload = {"event": "promotion.blocked", "prompt": "greeter", "to_version": 2}
    result = deliver_webhook(payload, url="https://hooks.example/p", secret="s3cret")

    assert result == {"status": "delivered", "code": 200}
    assert captured["url"] == "https://hooks.example/p"
    assert json.loads(captured["body"]) == payload
    expected = hmac.new(b"s3cret", captured["body"], hashlib.sha256).hexdigest()
    assert captured["headers"]["x-promptforge-signature"] == f"sha256={expected}"


def test_unsigned_when_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None):
        captured["headers"] = _lower_headers(request)
        return _FakeResponse(204)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = deliver_webhook({"event": "promotion.promoted"}, url="https://h/x", secret=None)
    assert result["status"] == "delivered"
    assert "x-promptforge-signature" not in captured["headers"]


def test_5xx_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None):
        raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(TransientWebhookError):
        deliver_webhook({"event": "x"}, url="https://h/x")


def test_4xx_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None):
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = deliver_webhook({"event": "x"}, url="https://h/x")
    assert result == {"status": "rejected", "code": 400}


def test_network_error_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(TransientWebhookError):
        deliver_webhook({"event": "x"}, url="https://h/x")
