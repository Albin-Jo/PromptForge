"""The trace-ingest task end to end, against a real Postgres.

The API integration suite tests ``persist_trace`` directly; this exercises the **task wrapper** —
``ingest_trace`` rebuilding a ``TraceEvent`` from the queue payload, opening ``session_scope``,
persisting, and reporting — through Celery's eager ``.apply()``. It closes the gap where the
wrapper itself (payload decode + session wiring) was previously uncovered.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from promptforge_api.db.trace_models import Trace
from promptforge_api.observability import TraceEvent
from promptforge_worker import db as worker_db
from promptforge_worker.tasks import ingest_trace


@pytest.fixture
def session_factory(
    worker_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> sessionmaker[Session]:
    """Point the worker's ``SessionLocal`` at the throwaway Postgres for the test (as the eval
    integration test does), so the task's own commit lands in the container we assert against."""
    factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "SessionLocal", factory)
    return factory


def test_ingest_trace_task_persists_with_computed_cost(
    session_factory: sessionmaker[Session],
) -> None:
    payload = TraceEvent(
        model="openai/gpt-4o-mini",
        status="ok",
        source="sdk",
        input_tokens=1000,
        output_tokens=500,
        latency_ms=200,
    ).to_dict()

    result = ingest_trace.apply(kwargs={"payload": payload}).get()
    assert result["status"] == "ingested"

    with session_factory() as session:
        stored = session.get(Trace, payload["id"])
        assert stored is not None
        assert stored.cost_usd == Decimal("0.000450")  # 1000*0.15/1e6 + 500*0.60/1e6
        assert stored.total_tokens == 1500
        assert stored.source == "sdk"


def test_ingest_trace_task_is_idempotent_on_redelivery(
    session_factory: sessionmaker[Session],
) -> None:
    payload = TraceEvent(
        model="openai/gpt-4o-mini", status="ok", input_tokens=10, output_tokens=10
    ).to_dict()

    ingest_trace.apply(kwargs={"payload": payload}).get()
    ingest_trace.apply(kwargs={"payload": payload}).get()  # redelivery of the same event

    with session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(Trace).where(Trace.id == payload["id"])
        )
        assert count == 1  # the second delivery wrote nothing — spend can't double-count
