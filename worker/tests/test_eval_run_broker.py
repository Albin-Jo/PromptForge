"""Real-broker coverage: a full eval run delivered through an actual worker.

The eager test (``test_eval_run_integration``) drives the task in-process and proves the pipeline
+ idempotency. This one closes the gap eager mode can't: that the task actually *travels* the
broker — enqueued by name, routed to the evals queue, consumed by a running worker — and lands
its scores. It replaces the Sprint 6 ``test_idempotency_broker`` (which proved the now-retired
Redis dedup stub) with the real thing: the run's results in Postgres after a round-trip.

The worker runs in-process (``start_worker``), so the same monkeypatches that point the task at a
throwaway Postgres and a fake gateway reach it. Uses the ``solo`` pool for deterministic delivery.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from promptforge_api.db.eval_models import Dataset, DatasetItem, EvalRun, ScoreRecord
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.gateway import LLMGateway
from promptforge_worker import db as worker_db
from promptforge_worker import tasks
from promptforge_worker.celery_app import app
from promptforge_worker.tasks import run_eval

_JUDGE_REPLY = '{"rationale": "correct", "rating": 5}'


@pytest.fixture
def patched_worker(worker_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    """Point the worker's DB + gateway + RAGAS at test doubles (used by the in-process worker)."""
    factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "SessionLocal", factory)

    async def backend(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            model="openai/gpt-4o-mini",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=_JUDGE_REPLY), finish_reason="stop")
            ],
            usage=None,
        )

    monkeypatch.setattr(tasks, "get_gateway", lambda: LLMGateway(backend))
    from ragas.metrics import FactualCorrectness

    async def fake_ragas(self: Any, sample: Any, *a: Any, **k: Any) -> float:
        return 0.8

    monkeypatch.setattr(FactualCorrectness, "single_turn_ascore", fake_ragas)
    return factory


@pytest.fixture
def broker_worker(redis_base_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Celery]:
    """Point the Celery app at the throwaway Redis and run an in-process worker draining it."""
    original_broker = app.conf.broker_url
    original_backend = app.conf.result_backend
    app.conf.broker_url = f"{redis_base_url}/1"
    app.conf.result_backend = f"{redis_base_url}/2"
    # NOTE (known fragility): this mutates the module-level `app` singleton's broker. If an earlier
    # test in the session already made the app pool a connection to the default broker, this repoint
    # may not take and the worker dials localhost:6379 instead of the container. In the real suite
    # this test sorts before the eager eval tests, so it runs first and is unaffected; it only
    # surfaces under manual reordering. Tracked in the learning backlog (a fresh per-test Celery app
    # is the robust fix). Mirrors the Sprint 6 broker test's pattern.
    try:
        with start_worker(app, perform_ping_check=False, pool="solo", loglevel="info"):
            yield app
    finally:
        app.conf.broker_url = original_broker
        app.conf.result_backend = original_backend


def _seed_run(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        prompt = Prompt(name=f"qa-{uuid.uuid4()}")
        version = PromptVersion(
            prompt=prompt,
            version_number=1,
            content="Answer: {{question}}",
            input_variables=["question"],
        )
        dataset = Dataset(
            name=f"golden-{uuid.uuid4()}",
            items=[DatasetItem(input="capital of France?", reference="Paris")],
        )
        session.add_all([prompt, version, dataset])
        session.flush()
        run = EvalRun(
            dataset_id=dataset.id,
            prompt_version_id=version.id,
            scorer_config=[{"scorer": "llm_judge"}, {"scorer": "ragas_factual_correctness"}],
            status="pending",
        )
        session.add(run)
        session.commit()
        return run.id


def test_eval_run_completes_over_the_broker(
    patched_worker: sessionmaker[Session], broker_worker: Celery
) -> None:
    run_id = _seed_run(patched_worker)

    # Enqueue by name → routed to the evals queue → consumed by the running worker.
    result = run_eval.delay(eval_run_id=str(run_id)).get(timeout=30)

    assert result["status"] == "completed"
    assert result["summary"]["scored"] == 2  # 1 item × 2 scorers

    with patched_worker() as session:
        run = session.get(EvalRun, run_id)
        assert run is not None and run.status == "completed"
        scores = list(session.scalars(select(ScoreRecord).where(ScoreRecord.eval_run_id == run_id)))
        assert {s.scorer_name for s in scores} == {"llm_judge", "ragas_factual_correctness"}
