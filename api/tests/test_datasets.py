"""Datasets API: list / edit / delete (Sprint 16f gap-fill) + the delete guard.

Exercised through the ``client`` fixture — i.e. router → service → repository → a real throwaway
Postgres (Testcontainers), the only way to catch the cascade/SET-NULL behaviour the edit and delete
semantics (ADR 0024) actually rely on. Create + get already existed; these cover the new surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.services.evals import DatasetItemInput, EvalService


def _create(client: TestClient, name: str, *, items: list[dict] | None = None) -> None:
    """Create a golden set with at least one case (the minimum the schema enforces)."""
    body = {
        "name": name,
        "description": "seed",
        "items": items or [{"input": "hi", "reference": "hello"}],
    }
    resp = client.post("/datasets", json=body)
    assert resp.status_code == 201, resp.text


def _attach_to_new_prompt(client: TestClient, prompt: str, dataset: str) -> None:
    """Create a prompt and point its golden set at ``dataset`` (sets up the delete guard)."""
    created = client.post(
        "/prompts", json={"name": prompt, "content": "Say {{x}}", "input_variables": ["x"]}
    )
    assert created.status_code == 201, created.text
    attached = client.put(f"/prompts/{prompt}/golden-set", json={"dataset": dataset})
    assert attached.status_code == 200, attached.text


# ----------------------------------------------------------------------------- list


def test_list_datasets_returns_each_with_its_case_count(client: TestClient) -> None:
    _create(client, "alpha", items=[{"input": "a"}, {"input": "b"}])
    _create(client, "beta", items=[{"input": "c"}])

    resp = client.get("/datasets")

    assert resp.status_code == 200
    rows = resp.json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["alpha"]["item_count"] == 2
    assert by_name["beta"]["item_count"] == 1


def test_list_datasets_is_name_ordered(client: TestClient) -> None:
    _create(client, "zeta")
    _create(client, "alpha")

    names = [r["name"] for r in client.get("/datasets").json()]

    assert names == sorted(names)


def test_list_datasets_empty(client: TestClient) -> None:
    assert client.get("/datasets").json() == []


# ----------------------------------------------------------------------------- detail


def test_get_dataset_returns_its_cases(client: TestClient) -> None:
    _create(
        client,
        "gs",
        items=[{"input": "q", "reference": "a", "metadata": {"tag": "x"}}, {"input": "q2"}],
    )

    body = client.get("/datasets/gs").json()

    assert body["item_count"] == 2
    assert body["items"] == [
        {"input": "q", "reference": "a", "metadata": {"tag": "x"}},
        {"input": "q2", "reference": None, "metadata": None},
    ]


# ----------------------------------------------------------------------------- update


def test_update_replaces_all_cases_wholesale(client: TestClient) -> None:
    _create(client, "gs", items=[{"input": "old1"}, {"input": "old2"}])

    resp = client.put(
        "/datasets/gs",
        json={"description": "edited", "items": [{"input": "new-only", "reference": "r"}]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "edited"
    # Replace, not merge: two old cases gone, one new case remains (ADR 0024).
    assert body["item_count"] == 1
    assert client.get("/datasets").json()[0]["item_count"] == 1


def test_update_unknown_dataset_is_404(client: TestClient) -> None:
    resp = client.put("/datasets/nope", json={"items": [{"input": "x"}]})
    assert resp.status_code == 404


def test_update_with_no_cases_is_rejected(client: TestClient) -> None:
    _create(client, "gs")
    # An empty golden set can't gate anything — schema requires >= 1 case.
    resp = client.put("/datasets/gs", json={"items": []})
    assert resp.status_code == 422


def test_update_bumps_updated_at_on_a_cases_only_edit(db_session: Session) -> None:
    # Service-level: a cases-only edit must still refresh updated_at, even though it dirties the
    # child rows and not the datasets row. now() is the txn timestamp (constant within this test's
    # transaction), so we force updated_at into the past first to make the bump observable.
    service = EvalService(
        EvalRepository(db_session), PromptRepository(db_session), submit_eval=lambda _id: None
    )
    dataset = service.create_dataset(
        name="gs", description="d", items=[DatasetItemInput(input="a")]
    )
    dataset.updated_at = datetime(2000, 1, 1, tzinfo=UTC)
    db_session.flush()

    # Same description, different cases — the bump is driven by the explicit touch, not description.
    service.update_dataset(name="gs", description="d", items=[DatasetItemInput(input="b")])

    assert dataset.updated_at.year != 2000


# ----------------------------------------------------------------------------- delete


def test_delete_unused_dataset_succeeds(client: TestClient) -> None:
    _create(client, "gs")

    resp = client.delete("/datasets/gs")

    assert resp.status_code == 204
    assert client.get("/datasets/gs").status_code == 404


def test_delete_unknown_dataset_is_404(client: TestClient) -> None:
    assert client.delete("/datasets/nope").status_code == 404


def test_delete_refuses_when_a_prompt_gates_on_it(client: TestClient) -> None:
    _create(client, "gated-set")
    _attach_to_new_prompt(client, "myprompt", "gated-set")

    resp = client.delete("/datasets/gated-set")

    # Fail-closed: a prompt still gates on it, so 409 with the offending name (ADR 0024).
    assert resp.status_code == 409, resp.text
    assert "myprompt" in resp.json()["detail"]
    # The set is still there — the guard didn't half-delete it.
    assert client.get("/datasets/gated-set").status_code == 200


def test_delete_succeeds_after_detaching(client: TestClient) -> None:
    _create(client, "gated-set")
    _attach_to_new_prompt(client, "myprompt", "gated-set")

    # Detach clears the prompt's golden set, which frees the dataset to be deleted.
    detached = client.delete("/prompts/myprompt/golden-set")
    assert detached.status_code == 200, detached.text

    assert client.delete("/datasets/gated-set").status_code == 204


# --------------------------------------------------------------- attach / detach exposure


def test_prompt_read_exposes_attached_golden_set_id(client: TestClient) -> None:
    _create(client, "gs")
    _attach_to_new_prompt(client, "p", "gs")

    gs_id = client.get("/datasets/gs").json()["id"]
    prompt = client.get("/prompts/p").json()

    assert prompt["golden_set_id"] == gs_id


def test_detach_clears_the_golden_set(client: TestClient) -> None:
    _create(client, "gs")
    _attach_to_new_prompt(client, "p", "gs")

    body = client.delete("/prompts/p/golden-set").json()

    assert body["golden_set_id"] is None
    assert client.get("/prompts/p").json()["golden_set_id"] is None
