"""Integration tests for the eval data model against a real throwaway Postgres.

These prove the DoD's "eval entities persist" clause the only way that's meaningful:
by running the actual migration (the ``engine`` fixture does ``upgrade head``) and
round-tripping rows through it — so a drift between the models and the migration, a
broken FK, or a bad ``ondelete`` rule shows up here, not in production.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import Dataset, DatasetItem, EvalRun, ScoreRecord


def _make_dataset(session: Session) -> Dataset:
    dataset = Dataset(
        name=f"golden-{uuid.uuid4()}",
        description="a small golden set",
        items=[
            DatasetItem(input="capital of France?", reference="Paris"),
            DatasetItem(input="say hello", reference=None, item_metadata={"tag": "smoke"}),
        ],
    )
    session.add(dataset)
    session.flush()
    return dataset


def test_dataset_with_items_round_trips(db_session: Session) -> None:
    dataset = _make_dataset(db_session)
    db_session.expire_all()  # force a re-read from the DB, not the identity map

    fetched = db_session.scalars(select(Dataset).where(Dataset.id == dataset.id)).one()
    assert fetched.created_at is not None  # server default fired
    assert len(fetched.items) == 2
    smoke = next(item for item in fetched.items if item.reference is None)
    assert smoke.item_metadata == {"tag": "smoke"}  # JSONB round-trips


def test_eval_run_owns_scores_and_summary_persists(db_session: Session) -> None:
    dataset = _make_dataset(db_session)
    run = EvalRun(
        dataset_id=dataset.id,
        scorer_config=[{"scorer": "llm_judge"}],
        status="completed",
        summary={"pass_rate": 0.5, "mean_value": 0.625, "count": 2},
        scores=[
            ScoreRecord(
                scorer_name="llm_judge",
                value=1.0,
                passed=True,
                rationale="correct",
                score_metadata={"rating": 5},
            ),
            ScoreRecord(scorer_name="llm_judge", value=0.25, passed=False, rationale="wrong"),
        ],
    )
    db_session.add(run)
    db_session.flush()
    db_session.expire_all()

    fetched = db_session.scalars(select(EvalRun).where(EvalRun.id == run.id)).one()
    assert fetched.status == "completed"
    assert fetched.summary == {"pass_rate": 0.5, "mean_value": 0.625, "count": 2}
    assert len(fetched.scores) == 2
    assert {s.passed for s in fetched.scores} == {True, False}


def test_ad_hoc_run_persists_without_dataset_or_version(db_session: Session) -> None:
    # The Sprint 7 demo: score one output, tied to no dataset and no prompt version.
    run = EvalRun(
        scorer_config=[{"scorer": "llm_judge"}],
        status="completed",
        scores=[ScoreRecord(scorer_name="llm_judge", value=1.0, passed=True, rationale="ok")],
    )
    db_session.add(run)
    db_session.flush()

    fetched = db_session.scalars(select(EvalRun).where(EvalRun.id == run.id)).one()
    assert fetched.dataset_id is None
    assert fetched.prompt_version_id is None
    assert len(fetched.scores) == 1


def test_deleting_a_run_cascades_to_its_scores(db_session: Session) -> None:
    run = EvalRun(
        scorer_config=[{"scorer": "llm_judge"}],
        scores=[ScoreRecord(scorer_name="llm_judge", value=0.5, passed=False, rationale="meh")],
    )
    db_session.add(run)
    db_session.flush()
    score_id = run.scores[0].id

    db_session.delete(run)
    db_session.flush()

    assert db_session.get(ScoreRecord, score_id) is None  # CASCADE removed the child


def test_deleting_a_dataset_nulls_the_runs_pointer_but_keeps_the_run(
    db_session: Session,
) -> None:
    dataset = _make_dataset(db_session)
    run = EvalRun(
        dataset_id=dataset.id, scorer_config=[{"scorer": "llm_judge"}], status="completed"
    )
    db_session.add(run)
    db_session.flush()

    db_session.delete(dataset)
    db_session.flush()
    db_session.expire_all()

    # SET NULL: the historical result survives the golden set being deleted.
    fetched = db_session.get(EvalRun, run.id)
    assert fetched is not None
    assert fetched.dataset_id is None


def test_score_value_outside_unit_range_is_rejected(db_session: Session) -> None:
    # The CHECK guards the data of record: an out-of-scale value would skew aggregates.
    run = EvalRun(
        scorer_config=[{"scorer": "llm_judge"}],
        scores=[
            ScoreRecord(
                scorer_name="llm_judge", value=2.0, passed=True, rationale="impossible value"
            )
        ],
    )
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_eval_run_invalid_status_is_rejected(db_session: Session) -> None:
    db_session.add(EvalRun(scorer_config=[{"scorer": "llm_judge"}], status="banana"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_eval_run_status_defaults_to_pending(db_session: Session) -> None:
    run = EvalRun(scorer_config=[{"scorer": "llm_judge"}])
    db_session.add(run)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(EvalRun, run.id).status == "pending"
