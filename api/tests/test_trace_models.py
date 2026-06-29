"""Integration tests for the Trace model against a real throwaway Postgres (Phase 7).

Proves "trace entities persist" the meaningful way — by running the actual migration (the
``engine`` fixture does ``upgrade head``) and round-tripping rows: a bad FK, a wrong ``ondelete``,
or a Numeric that doesn't survive as a Decimal shows up here, not in production.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.trace_models import Trace
from promptforge_api.pricing import cost_for


def _version(session: Session) -> PromptVersion:
    prompt = Prompt(name=f"qa-{uuid.uuid4()}")
    version = PromptVersion(
        prompt=prompt, version_number=1, content="hi {{x}}", input_variables=["x"]
    )
    session.add_all([prompt, version])
    session.flush()
    return version


def test_trace_round_trips_with_computed_cost(db_session: Session) -> None:
    version = _version(db_session)
    cost = cost_for("openai/gpt-4o-mini", 1000, 500)
    trace = Trace(
        prompt_id=version.prompt_id,
        prompt_version_id=version.id,
        request_id="req-123",
        source="eval",
        provider="openai",
        model="openai/gpt-4o-mini",
        provider_model="gpt-4o-mini-2024-07-18",
        input="hi world",
        output="hello",
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        cost_usd=cost,
        latency_ms=320,
        status="ok",
    )
    db_session.add(trace)
    db_session.flush()
    db_session.expire_all()  # force a re-read from the DB, not the identity map

    fetched = db_session.get(Trace, trace.id)
    assert fetched is not None
    assert fetched.created_at is not None  # server default fired
    assert fetched.status == "ok"
    assert fetched.total_tokens == 1500
    # Numeric survives the round-trip as an exact Decimal, equal to what pricing computed.
    assert fetched.cost_usd == cost == Decimal("0.000450")


def test_trace_invalid_status_is_rejected(db_session: Session) -> None:
    db_session.add(Trace(model="openai/gpt-4o-mini", status="weird"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_trace_persists_without_any_prompt_linkage(db_session: Session) -> None:
    # A raw gateway call may belong to no registered prompt — both FKs are nullable.
    trace = Trace(model="openai/gpt-4o-mini", status="ok")
    db_session.add(trace)
    db_session.flush()

    fetched = db_session.get(Trace, trace.id)
    assert fetched is not None
    assert fetched.prompt_id is None
    assert fetched.prompt_version_id is None
    assert fetched.cost_usd is None  # no tokens → no cost


def test_deleting_a_version_nulls_the_trace_pointer_but_keeps_the_trace(
    db_session: Session,
) -> None:
    version = _version(db_session)
    trace = Trace(prompt_version_id=version.id, model="openai/gpt-4o-mini", status="ok")
    db_session.add(trace)
    db_session.flush()

    db_session.delete(version)
    db_session.flush()
    db_session.expire_all()

    # SET NULL: the historical spend record survives the version being deleted.
    fetched = db_session.get(Trace, trace.id)
    assert fetched is not None
    assert fetched.prompt_version_id is None
