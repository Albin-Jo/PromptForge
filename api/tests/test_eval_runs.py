"""Integration tests for the per-version eval run-history endpoint (Sprint 24, T1).

``GET /prompts/{name}/versions/{n}/evals`` lists every persisted eval run for a version, newest
first — the audit trail behind the latest-only ``/eval`` status. Driven through the API over a
real Postgres; the eval *execution* is the worker's job, so a completed run is simulated by
writing a crafted ``summary`` (the same shortcut the promotion-gate suite uses).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import EvalRun


def _seed_gated_prompt(client: TestClient, name: str) -> None:
    """Create a prompt and attach a one-case golden set so evals can be triggered for it."""
    assert (
        client.post(
            "/datasets",
            json={"name": f"{name}-golden", "items": [{"input": "hi", "reference": "hello"}]},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/prompts",
            json={"name": name, "content": "Say {{x}}", "input_variables": ["x"]},
        ).status_code
        == 201
    )
    assert (
        client.put(f"/prompts/{name}/golden-set", json={"dataset": f"{name}-golden"}).status_code
        == 200
    )


def _complete_latest_run(session: Session, prompt_version_id: uuid.UUID, pass_rate: float) -> None:
    """Mark a version's most recent eval run completed with a crafted single-scorer summary."""
    run = session.scalars(
        select(EvalRun)
        .where(EvalRun.prompt_version_id == prompt_version_id)
        .order_by(EvalRun.created_at.desc())
    ).first()
    assert run is not None
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    run.summary = {
        "items": 1,
        "scored": 1,
        "errors": 0,
        "scorers": {
            "llm_judge": {"count": 1, "passed": 1, "pass_rate": pass_rate, "mean_value": pass_rate}
        },
    }
    session.flush()


def test_lists_runs_newest_first_with_summary(client: TestClient, db_session: Session) -> None:
    _seed_gated_prompt(client, "greeter")
    version_id = uuid.UUID(client.get("/prompts/greeter").json()["versions"][0]["id"])

    # Two on-demand evals → two runs; complete the newest so its summary is populated.
    assert client.post("/prompts/greeter/versions/1/evaluate").status_code == 202
    assert client.post("/prompts/greeter/versions/1/evaluate").status_code == 202
    _complete_latest_run(db_session, version_id, pass_rate=1.0)

    resp = client.get("/prompts/greeter/versions/1/evals")

    assert resp.status_code == 200, resp.text
    runs = resp.json()
    assert len(runs) == 2
    # Newest first: the completed run leads, carrying its scorers + summary.
    assert runs[0]["status"] == "completed"
    assert runs[0]["scorers"] == ["llm_judge"]
    assert runs[0]["summary"]["scorers"]["llm_judge"]["pass_rate"] == 1.0
    assert runs[0]["completed_at"] is not None
    # The older run is still pending and carries no summary yet.
    assert runs[1]["status"] == "pending"
    assert runs[1]["summary"] is None


def test_empty_when_no_runs(client: TestClient) -> None:
    # A prompt with no golden set and no triggered evals has an empty history (not a 404).
    assert (
        client.post(
            "/prompts", json={"name": "fresh", "content": "Hi {{x}}", "input_variables": ["x"]}
        ).status_code
        == 201
    )
    resp = client.get("/prompts/fresh/versions/1/evals")
    assert resp.status_code == 200
    assert resp.json() == []


def test_unknown_prompt_is_404(client: TestClient) -> None:
    assert client.get("/prompts/nope/versions/1/evals").status_code == 404


def test_unknown_version_is_404(client: TestClient) -> None:
    assert (
        client.post(
            "/prompts", json={"name": "fresh", "content": "Hi {{x}}", "input_variables": ["x"]}
        ).status_code
        == 201
    )
    assert client.get("/prompts/fresh/versions/999/evals").status_code == 404
