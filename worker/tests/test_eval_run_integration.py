"""The Sprint 8 DoD test: a full async eval run, end to end, against a real Postgres.

This is the clause the sprint turns on — *"an eval run picks 'LLM-judge + a RAGAS metric', runs
on the worker, stores per-item + aggregate scores."* We seed a prompt version + a golden set + an
``EvalRun`` configured with **both** scorers, run the real ``run_eval`` task, and assert the rows
and summary it leaves behind.

What's real vs faked: the runner, the task lifecycle, the registry, the judge, the schema, and
the migration are all real (the run executes through the actual async pipeline and writes to a
throwaway Postgres). Only the two deepest external dependencies are stubbed so the test needs no
network or key — the **gateway** (a fake backend returns a judge-shaped JSON reply, which doubles
as each item's generated output) and **RAGAS's internal scoring** (its multi-call LLM pipeline is
patched to a fixed score). A real-model end-to-end is left to a key-gated test, as with the judge.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from promptforge_api.db.eval_models import Dataset, DatasetItem, EvalRun, ScoreRecord
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.gateway import LLMGateway
from promptforge_worker import db as worker_db
from promptforge_worker import tasks
from promptforge_worker.tasks import run_eval

# The fake gateway always returns a valid judge verdict. It serves double duty: as each item's
# *generated output* (what the judge/RAGAS then grade) and as the judge's *reply* (parsed to a
# rating). Rating 5 → value 1.0 → passes the judge's default threshold.
_JUDGE_REPLY = '{"rationale": "the answer is correct and relevant", "rating": 5}'


@pytest.fixture
def session_factory(
    worker_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> sessionmaker[Session]:
    """Bind the worker's session factory to the throwaway Postgres for the duration of a test.

    ``session_scope`` opens ``promptforge_worker.db.SessionLocal``; pointing that at the test
    engine makes the task's own commits land in the container we seeded and assert against.
    """
    factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "SessionLocal", factory)
    return factory


@pytest.fixture
def fake_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the task's gateway accessor and RAGAS's scorer at fakes (no network/key)."""

    async def backend(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            model="openai/gpt-4o-mini",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=_JUDGE_REPLY), finish_reason="stop")
            ],
            usage=None,
        )

    monkeypatch.setattr(tasks, "get_gateway", lambda: LLMGateway(backend))

    # RAGAS FactualCorrectness runs a multi-call LLM pipeline internally; patch its async score to
    # a fixed f1 so the test exercises *our* adapter + persistence, not RAGAS's prompts.
    from ragas.metrics import FactualCorrectness

    async def fake_ragas_score(self: Any, sample: Any, *a: Any, **k: Any) -> float:
        return 0.8

    monkeypatch.setattr(FactualCorrectness, "single_turn_ascore", fake_ragas_score)


@pytest.fixture
def seeded_run(session_factory: sessionmaker[Session]) -> uuid.UUID:
    """Create a prompt version + a 2-item golden set + a judge-and-RAGAS run; return the run id."""
    with session_factory() as session:
        prompt = Prompt(name=f"qa-{uuid.uuid4()}")
        version = PromptVersion(
            prompt=prompt,
            version_number=1,
            content="Answer concisely: {{question}}",
            input_variables=["question"],
        )
        dataset = Dataset(
            name=f"golden-{uuid.uuid4()}",
            items=[
                DatasetItem(input="capital of France?", reference="Paris"),
                DatasetItem(input="2+2?", reference="4"),
            ],
        )
        session.add_all([prompt, version, dataset])
        session.flush()
        run = EvalRun(
            dataset_id=dataset.id,
            prompt_version_id=version.id,
            scorer_config=[
                {"scorer": "llm_judge"},
                {"scorer": "ragas_factual_correctness"},
            ],
            status="pending",
        )
        session.add(run)
        session.commit()
        return run.id


def test_full_async_eval_run_stores_per_item_and_aggregate_scores(
    seeded_run: uuid.UUID, fake_gateway: None, session_factory: sessionmaker[Session]
) -> None:
    result = run_eval.apply(kwargs={"eval_run_id": str(seeded_run)}).get()

    # --- the task's own report ---
    assert result["status"] == "completed"
    summary = result["summary"]
    assert summary["items"] == 2
    assert summary["errors"] == 0
    assert summary["scored"] == 4  # 2 items × 2 scorers
    # per-scorer aggregates are present and computed
    assert summary["scorers"]["llm_judge"]["pass_rate"] == 1.0
    assert summary["scorers"]["llm_judge"]["mean_value"] == 1.0
    assert summary["scorers"]["ragas_factual_correctness"]["mean_value"] == pytest.approx(0.8)

    # --- the persisted rows ---
    with session_factory() as session:
        run = session.get(EvalRun, seeded_run)
        assert run is not None
        assert run.status == "completed"
        assert run.completed_at is not None

        scores = list(
            session.scalars(select(ScoreRecord).where(ScoreRecord.eval_run_id == seeded_run))
        )
        assert len(scores) == 4
        # each (item, scorer) verdict is tagged with the scorer that made it
        assert {s.scorer_name for s in scores} == {"llm_judge", "ragas_factual_correctness"}
        # every score links back to a dataset item
        assert all(s.dataset_item_id is not None for s in scores)


def test_rerunning_a_completed_run_is_idempotent(
    seeded_run: uuid.UUID, fake_gateway: None, session_factory: sessionmaker[Session]
) -> None:
    first = run_eval.apply(kwargs={"eval_run_id": str(seeded_run)}).get()
    second = run_eval.apply(kwargs={"eval_run_id": str(seeded_run)}).get()

    assert "deduplicated" not in first
    assert second["deduplicated"] is True  # the run was already completed
    assert second["summary"] == first["summary"]

    # The heart of "runs once": the second submission wrote NO new score rows.
    with session_factory() as session:
        scores = list(
            session.scalars(select(ScoreRecord).where(ScoreRecord.eval_run_id == seeded_run))
        )
        assert len(scores) == 4
