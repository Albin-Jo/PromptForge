"""Integration tests for the promotion gate end-to-end, over HTTP + a real Postgres.

These cover the Sprint 11 DoD: a worse prompt is detected, promotion is refused with the
failing scores attached, an audit row is written, and a webhook fires. The eval *execution*
(generate → score on the worker) is already covered by the worker suite, so here we simulate a
completed eval by writing a crafted ``summary`` — the focus is the **gate's** decision, audit,
and notification, driven through the API exactly as a client would.

The gate's two side-effecting callables (enqueue an eval, deliver a webhook) are replaced with
in-memory recorders, so the tests need no broker and can assert what *would* be enqueued/sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.cache import NullCache
from promptforge_api.db.engine import get_session
from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.promotion_models import PromotionAudit
from promptforge_api.main import create_app
from promptforge_api.promotion import PromotionPolicy
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.promotion import PromotionAuditRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.routers import datasets as datasets_router
from promptforge_api.routers import prompts as prompts_router
from promptforge_api.services.evals import EvalService
from promptforge_api.services.promotion import PromotionGate
from promptforge_api.services.prompts import PromptService

# min_dataset_size=3 so a small test golden set still exercises the regression check.
_TEST_POLICY = PromotionPolicy(
    gated_label="production", min_quality=0.7, max_quality_drop=0.05, min_dataset_size=3
)


@pytest.fixture
def recorders() -> SimpleNamespace:
    """Captures what the gate would enqueue (eval run ids) and send (webhook payloads)."""
    return SimpleNamespace(evals=[], webhooks=[])


@pytest.fixture
def gate_client(db_session: Session, recorders: SimpleNamespace) -> Iterator[TestClient]:
    """A TestClient whose prompt/eval services use the test session + recorder callables."""

    def _override_session() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    def submit_eval(eval_run_id: uuid.UUID) -> None:
        recorders.evals.append(eval_run_id)

    def submit_webhook(payload: dict) -> None:
        recorders.webhooks.append(payload)

    def _eval_service() -> EvalService:
        return EvalService(
            EvalRepository(db_session), PromptRepository(db_session), submit_eval=submit_eval
        )

    def override_prompt_service() -> PromptService:
        gate = PromotionGate(
            _eval_service(),
            PromotionAuditRepository(db_session),
            policy=_TEST_POLICY,
            submit_webhook=submit_webhook,
        )
        return PromptService(
            PromptRepository(db_session),
            NullCache(),
            composition=CompositionRepository(db_session),
            gate=gate,
        )

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[prompts_router.get_prompt_service] = override_prompt_service
    app.dependency_overrides[prompts_router.get_eval_service] = _eval_service
    app.dependency_overrides[datasets_router.get_eval_service] = _eval_service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _complete_eval(
    session: Session, version_id: uuid.UUID, pass_rate: float, *, items: int = 3
) -> EvalRun:
    """Simulate the worker finishing a version's latest eval with a crafted pass-rate summary."""
    run = session.scalars(
        select(EvalRun)
        .where(EvalRun.prompt_version_id == version_id)
        .order_by(EvalRun.created_at.desc())
    ).first()
    assert run is not None, "expected an eval run to exist for this version"
    passed = round(pass_rate * items)
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    run.summary = {
        "items": items,
        "scored": items,
        "errors": 0,
        "error_details": [],
        "scorers": {
            "llm_judge": {
                "count": items,
                "passed": passed,
                "pass_rate": pass_rate,
                "mean_value": pass_rate,
            }
        },
    }
    session.flush()
    return run


def _seed_golden_set(client: TestClient, name: str) -> None:
    resp = client.post(
        "/datasets",
        json={
            "name": name,
            "items": [
                {"input": "hi", "reference": "hello"},
                {"input": "bye", "reference": "goodbye"},
                {"input": "ta", "reference": "thanks"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text


def _seed_production(client: TestClient, session: Session, prompt: str) -> str:
    """Create a gated prompt, attach a golden set, and put a good v1 in production."""
    _seed_golden_set(client, f"{prompt}-golden")
    created = client.post(
        "/prompts", json={"name": prompt, "content": "Say {{x}}", "input_variables": ["x"]}
    )
    assert created.status_code == 201, created.text
    v1_id = created.json()["versions"][0]["id"]
    attached = client.put(f"/prompts/{prompt}/golden-set", json={"dataset": f"{prompt}-golden"})
    assert attached.status_code == 200, attached.text
    assert client.post(f"/prompts/{prompt}/versions/1/evaluate").status_code == 202
    _complete_eval(session, uuid.UUID(v1_id), 0.9)
    promoted = client.put(f"/prompts/{prompt}/labels/production", json={"version_number": 1})
    assert promoted.status_code == 200, promoted.text
    return v1_id


def _add_version(client: TestClient, prompt: str, content: str) -> str:
    resp = client.post(
        f"/prompts/{prompt}/versions", json={"content": content, "input_variables": ["x"]}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------- the DoD path
def test_worse_prompt_is_refused_with_scores_and_fires_webhook(
    gate_client: TestClient, db_session: Session, recorders: SimpleNamespace
) -> None:
    _seed_production(gate_client, db_session, "greeter")
    # A candidate that clears the floor (0.80) but regresses 0.10 below production (0.90 > 0.05).
    v2_id = _add_version(gate_client, "greeter", "Say {{x}} please")
    _complete_eval(db_session, uuid.UUID(v2_id), 0.80)

    resp = gate_client.put("/prompts/greeter/labels/production", json={"version_number": 2})

    assert resp.status_code == 409
    body = resp.json()
    assert "regressed" in body["detail"]
    assert body["promotion"]["deltas"][0]["regression"] is True
    # The webhook fired on the block...
    assert any(w["event"] == "promotion.blocked" for w in recorders.webhooks)
    # ...a blocked audit was recorded...
    blocked = db_session.scalars(
        select(PromotionAudit).where(PromotionAudit.decision == "blocked")
    ).all()
    assert len(blocked) == 1
    assert blocked[0].to_version_number == 2 and blocked[0].from_version_number == 1
    # ...and production still points at the good v1.
    assert gate_client.get("/prompts/greeter/labels/production").json()["version_number"] == 1


def test_below_floor_candidate_is_refused(gate_client: TestClient, db_session: Session) -> None:
    _seed_production(gate_client, db_session, "p")
    v2_id = _add_version(gate_client, "p", "Say {{x}} now")
    _complete_eval(db_session, uuid.UUID(v2_id), 0.50)  # below the 0.70 floor

    resp = gate_client.put("/prompts/p/labels/production", json={"version_number": 2})
    assert resp.status_code == 409
    assert "below the floor" in resp.json()["detail"]


def test_good_candidate_is_promoted_with_audit_and_webhook(
    gate_client: TestClient, db_session: Session, recorders: SimpleNamespace
) -> None:
    _seed_production(gate_client, db_session, "ok")
    v2_id = _add_version(gate_client, "ok", "Say {{x}} kindly")
    _complete_eval(db_session, uuid.UUID(v2_id), 0.90)  # no regression

    resp = gate_client.put("/prompts/ok/labels/production", json={"version_number": 2})
    assert resp.status_code == 200
    assert resp.json()["version"]["version_number"] == 2
    assert any(w["event"] == "promotion.promoted" for w in recorders.webhooks)
    promoted = db_session.scalars(
        select(PromotionAudit).where(PromotionAudit.decision == "promoted")
    ).all()
    # two promotions: v1 (seed) and v2.
    assert {a.to_version_number for a in promoted} == {1, 2}


def test_promotion_pending_while_eval_unfinished(gate_client: TestClient) -> None:
    _seed_golden_set(gate_client, "pend-golden")
    gate_client.post(
        "/prompts", json={"name": "pend", "content": "Say {{x}}", "input_variables": ["x"]}
    )
    gate_client.put("/prompts/pend/golden-set", json={"dataset": "pend-golden"})
    gate_client.post("/prompts/pend/versions/1/evaluate")  # pending, never completed

    resp = gate_client.put("/prompts/pend/labels/production", json={"version_number": 1})
    assert resp.status_code == 409
    assert "eval_run_id" in resp.json()
    assert "progress" in resp.json()["detail"]


def test_promotion_without_golden_set_is_refused(gate_client: TestClient) -> None:
    gate_client.post(
        "/prompts", json={"name": "bare", "content": "Say {{x}}", "input_variables": ["x"]}
    )
    resp = gate_client.put("/prompts/bare/labels/production", json={"version_number": 1})
    assert resp.status_code == 409
    assert "no golden set" in resp.json()["detail"]


def test_non_gated_label_moves_freely(gate_client: TestClient) -> None:
    gate_client.post(
        "/prompts", json={"name": "stg", "content": "Say {{x}}", "input_variables": ["x"]}
    )
    resp = gate_client.put("/prompts/stg/labels/staging", json={"version_number": 1})
    assert resp.status_code == 200
    assert resp.json()["version"]["version_number"] == 1


def test_eval_status_endpoint_reports_summary(gate_client: TestClient, db_session: Session) -> None:
    _seed_golden_set(gate_client, "st-golden")
    created = gate_client.post(
        "/prompts", json={"name": "st", "content": "Say {{x}}", "input_variables": ["x"]}
    )
    v1_id = created.json()["versions"][0]["id"]
    gate_client.put("/prompts/st/golden-set", json={"dataset": "st-golden"})

    # Before any eval: unevaluated.
    assert gate_client.get("/prompts/st/versions/1/eval").json()["status"] == "unevaluated"

    gate_client.post("/prompts/st/versions/1/evaluate")
    _complete_eval(db_session, uuid.UUID(v1_id), 0.9)

    status = gate_client.get("/prompts/st/versions/1/eval").json()
    assert status["status"] == "completed"
    assert status["summary"]["scorers"]["llm_judge"]["pass_rate"] == 0.9


def test_attach_missing_dataset_is_404(gate_client: TestClient) -> None:
    gate_client.post(
        "/prompts", json={"name": "nogs", "content": "Say {{x}}", "input_variables": ["x"]}
    )
    resp = gate_client.put("/prompts/nogs/golden-set", json={"dataset": "does-not-exist"})
    assert resp.status_code == 404


def test_create_and_read_dataset(gate_client: TestClient) -> None:
    resp = gate_client.post(
        "/datasets",
        json={"name": "ds1", "description": "smoke", "items": [{"input": "a", "reference": "b"}]},
    )
    assert resp.status_code == 201
    assert resp.json()["item_count"] == 1
    got = gate_client.get("/datasets/ds1")
    assert got.status_code == 200
    assert got.json()["name"] == "ds1"
