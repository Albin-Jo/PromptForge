"""Trace ingestion: persistence core + the SDK -> /traces -> persist path end-to-end.

Two layers, both against a real throwaway Postgres (the ``db_session`` fixture):

1. :func:`persist_trace` directly — that cost is computed from the pricing table, the version
   link is stored, and a redelivered event is idempotent (no double-counted spend).
2. The full path — the real SDK calling the real ``POST /traces`` endpoint, with the broker
   hop faked so the enqueued event is persisted synchronously in the test's transaction. This
   is the DoD's "integration test of trace ingestion": a trace lands, linked to its version.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promptforge import PromptForgeClient
from promptforge_api.db.engine import get_session
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.trace_models import Trace
from promptforge_api.main import create_app
from promptforge_api.observability import TraceEvent, persist_trace


# --------------------------------------------------------------------- persist_trace (unit-ish)
def test_persist_trace_computes_cost_and_derives_total_tokens(db_session: Session) -> None:
    event = TraceEvent(
        model="openai/gpt-4o-mini",
        status="ok",
        source="sdk",
        input_tokens=1000,
        output_tokens=500,
        latency_ms=120,
    )
    persist_trace(db_session, event)

    stored = db_session.get(Trace, event.id)
    assert stored is not None
    # 1000 * 0.15/1e6 + 500 * 0.60/1e6 = 0.000150 + 0.000300 = 0.000450
    assert stored.cost_usd == Decimal("0.000450")
    assert stored.total_tokens == 1500  # derived from input+output (emitter didn't send it)
    assert stored.source == "sdk"
    assert stored.status == "ok"


def test_persist_trace_leaves_cost_null_for_unpriced_model(db_session: Session) -> None:
    event = TraceEvent(model="some/unlisted-model", status="ok", input_tokens=10, output_tokens=10)
    persist_trace(db_session, event)

    stored = db_session.get(Trace, event.id)
    assert stored is not None
    assert stored.cost_usd is None  # honestly absent, never a guessed 0


def test_persist_trace_is_idempotent_on_id(db_session: Session) -> None:
    """A redelivered event (same id) writes nothing the second time — spend can't double-count."""
    event = TraceEvent(
        model="openai/gpt-4o-mini", status="ok", input_tokens=1000, output_tokens=500
    )
    persist_trace(db_session, event)
    persist_trace(db_session, event)  # redelivery

    count = db_session.scalar(select(func.count()).select_from(Trace).where(Trace.id == event.id))
    assert count == 1


def test_persist_trace_links_to_a_real_version(db_session: Session) -> None:
    prompt = Prompt(name="traced")
    prompt.versions.append(
        PromptVersion(version_number=1, content="hi {{x}}", input_variables=["x"])
    )
    db_session.add(prompt)
    db_session.flush()
    version = prompt.versions[0]

    event = TraceEvent(
        model="openai/gpt-4o-mini",
        status="ok",
        prompt_id=version.prompt_id,
        prompt_version_id=version.id,
        input_tokens=1,
        output_tokens=1,
    )
    persist_trace(db_session, event)

    stored = db_session.get(Trace, event.id)
    assert stored is not None
    assert stored.prompt_version_id == version.id
    assert stored.prompt_id == version.prompt_id


# --------------------------------------------------------------------- SDK -> /traces end-to-end
def _bind_session(app: FastAPI, db_session: Session) -> None:
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
            request.method, str(request.url), content=request.content, headers=request.headers
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    return PromptForgeClient("http://testserver", transport=httpx.MockTransport(handler), **kwargs)


@pytest.fixture
def seeded(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, PromptForgeClient]]:
    """App + SDK over it, with the trace-ingest enqueue faked to persist synchronously.

    The real endpoint enqueues to Celery; here we replace ``enqueue`` so the event is written
    straight into the test's transaction (the broker contract itself is tested in the worker
    suite). This keeps the whole SDK -> API -> persist path in one rolled-back transaction.
    """

    def fake_enqueue(task_name: str, *_args: object, **kwargs: object) -> None:
        payload = kwargs["payload"]
        assert isinstance(payload, dict)
        persist_trace(db_session, TraceEvent.from_dict(payload))

    monkeypatch.setattr("promptforge_api.routers.traces.enqueue", fake_enqueue)

    app = create_app()
    _bind_session(app, db_session)
    seed = TestClient(app)
    yield seed, _sdk_over(seed)
    app.dependency_overrides.clear()


def _seed_prompt(seed: TestClient) -> None:
    body = {
        "name": "traced",
        "content": "Hello {{name}}",
        "input_variables": ["name"],
        "model_settings": {"model": "openai/gpt-4o-mini"},
    }
    assert seed.post("/prompts", json=body).status_code == 201
    label = seed.put("/prompts/traced/labels/staging", json={"version_number": 1})
    assert label.status_code == 200


def test_sdk_records_a_version_linked_trace_end_to_end(
    seeded: tuple[TestClient, PromptForgeClient], db_session: Session
) -> None:
    seed, sdk = seeded
    _seed_prompt(seed)

    rendered = sdk.get_prompt("traced", label="staging", variables={"name": "Ada"})
    trace_id = sdk.record_trace(
        rendered, input_tokens=1000, output_tokens=500, latency_ms=200, status="ok"
    )

    assert trace_id is not None
    stored = db_session.scalar(select(Trace).where(Trace.id == trace_id))
    assert stored is not None
    assert str(stored.prompt_version_id) == rendered.prompt_version_id  # linked to the version
    assert stored.source == "sdk"
    assert stored.model == "openai/gpt-4o-mini"
    assert stored.cost_usd == Decimal("0.000450")  # computed server-side


def test_traces_endpoint_returns_202(seeded: tuple[TestClient, PromptForgeClient]) -> None:
    seed, _ = seeded
    response = seed.post("/traces", json={"model": "openai/gpt-4o-mini", "status": "ok"})
    assert response.status_code == 202
    assert "trace_id" in response.json()
