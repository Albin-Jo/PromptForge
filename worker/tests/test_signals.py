"""Unit tests for the worker-side correlation-id signal handlers.

The propagation plumbing (producer injects request_id into headers → worker binds it for
logging) is a CLAUDE.md non-negotiable but is otherwise only exercised by hand. These tests
guard the worker half: that an inbound request_id is bound to structlog's context and is
cleared afterwards, so a header-name typo or a missing clear can't slip through silently.
"""

from types import SimpleNamespace

import structlog

from promptforge_worker.signals import REQUEST_ID_HEADER, bind_request_id, clear_request_id


def _fake_task(request_id: object) -> SimpleNamespace:
    """A stand-in for a Celery Task whose request carries (or omits) a request id."""
    return SimpleNamespace(request=SimpleNamespace(**{REQUEST_ID_HEADER: request_id}))


def test_bind_request_id_binds_inbound_id() -> None:
    structlog.contextvars.clear_contextvars()
    bind_request_id(task=_fake_task("req-abc"))
    assert structlog.contextvars.get_contextvars().get("request_id") == "req-abc"
    clear_request_id()


def test_bind_request_id_noop_without_id() -> None:
    structlog.contextvars.clear_contextvars()
    bind_request_id(task=_fake_task(None))
    assert "request_id" not in structlog.contextvars.get_contextvars()


def test_clear_request_id_clears_context() -> None:
    structlog.contextvars.bind_contextvars(request_id="req-xyz")
    clear_request_id()
    assert "request_id" not in structlog.contextvars.get_contextvars()
