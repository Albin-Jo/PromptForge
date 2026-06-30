"""Integration tests for the trace read endpoints (Sprint 24, T3/T4).

``GET /traces`` pages a prompt's executions newest-first (lean: no rendered prompt/output);
``GET /traces/{id}`` returns one execution in full. Traces are normally worker-written, so the
tests seed ``Trace`` rows directly (the read path is what's under test, not ingestion).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.trace_models import Trace


def _create_prompt(client: TestClient, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    resp = client.post(
        "/prompts", json={"name": name, "content": "Say {{x}}", "input_variables": ["x"]}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return uuid.UUID(body["id"]), uuid.UUID(body["versions"][0]["id"])


def _seed_trace(
    session: Session,
    *,
    prompt_id: uuid.UUID | None,
    version_id: uuid.UUID | None,
    minute: int,
    model: str = "gpt-4o",
    status: str = "ok",
) -> uuid.UUID:
    trace = Trace(
        prompt_id=prompt_id,
        prompt_version_id=version_id,
        source="sdk",
        provider="openai",
        model=model,
        provider_model=f"{model}-2026",
        input="RENDERED PROMPT",
        output="MODEL OUTPUT",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cost_usd=Decimal("0.000450"),
        latency_ms=1234,
        status=status,
        created_at=datetime(2026, 6, 29, 12, minute, 0, tzinfo=UTC),
    )
    session.add(trace)
    session.flush()
    return trace.id


def test_list_is_newest_first_and_lean(client: TestClient, db_session: Session) -> None:
    prompt_id, version_id = _create_prompt(client, "greeter")
    _seed_trace(db_session, prompt_id=prompt_id, version_id=version_id, minute=1)
    newest = _seed_trace(db_session, prompt_id=prompt_id, version_id=version_id, minute=5)

    resp = client.get("/traces", params={"prompt": "greeter"})

    assert resp.status_code == 200, resp.text
    traces = resp.json()
    assert len(traces) == 2
    # Newest first, and the lean summary carries cost/latency/model/status but not rendered text.
    assert traces[0]["id"] == str(newest)
    assert traces[0]["cost_usd"] == "0.000450"  # exact decimal string, never a float
    assert traces[0]["latency_ms"] == 1234
    assert traces[0]["model"] == "gpt-4o"
    assert "input" not in traces[0]
    assert "output" not in traces[0]


def test_list_filters_by_version(client: TestClient, db_session: Session) -> None:
    prompt_id, version_id = _create_prompt(client, "greeter")
    # A trace on this version, and one for the prompt but no version (a raw call).
    on_version = _seed_trace(db_session, prompt_id=prompt_id, version_id=version_id, minute=2)
    _seed_trace(db_session, prompt_id=prompt_id, version_id=None, minute=3)

    resp = client.get("/traces", params={"prompt": "greeter", "version": 1})
    assert resp.status_code == 200
    traces = resp.json()
    assert [t["id"] for t in traces] == [str(on_version)]


def test_pagination_limits_and_offsets(client: TestClient, db_session: Session) -> None:
    prompt_id, version_id = _create_prompt(client, "greeter")
    ids = [
        _seed_trace(db_session, prompt_id=prompt_id, version_id=version_id, minute=m)
        for m in range(1, 4)
    ]  # minutes 1,2,3 → newest is minute 3

    page1 = client.get("/traces", params={"prompt": "greeter", "limit": 2, "offset": 0}).json()
    page2 = client.get("/traces", params={"prompt": "greeter", "limit": 2, "offset": 2}).json()
    assert [t["id"] for t in page1] == [str(ids[2]), str(ids[1])]
    assert [t["id"] for t in page2] == [str(ids[0])]


def test_detail_returns_full_execution(client: TestClient, db_session: Session) -> None:
    prompt_id, version_id = _create_prompt(client, "greeter")
    trace_id = _seed_trace(db_session, prompt_id=prompt_id, version_id=version_id, minute=1)

    resp = client.get(f"/traces/{trace_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["input"] == "RENDERED PROMPT"
    assert body["output"] == "MODEL OUTPUT"
    assert body["total_tokens"] == 15
    assert body["provider_model"] == "gpt-4o-2026"


def test_detail_unknown_trace_is_404(client: TestClient) -> None:
    assert client.get(f"/traces/{uuid.uuid4()}").status_code == 404


def test_list_unknown_prompt_is_404(client: TestClient) -> None:
    assert client.get("/traces", params={"prompt": "nope"}).status_code == 404


def test_list_version_without_prompt_is_422(client: TestClient) -> None:
    assert client.get("/traces", params={"version": 1}).status_code == 422
