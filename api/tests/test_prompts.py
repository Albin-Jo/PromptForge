"""Integration tests for the prompt registry against a real Postgres."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from promptforge_api.db.models import Prompt, PromptVersion


def _create(client: TestClient, **overrides: object) -> dict:
    """Create a prompt with sensible defaults; return the response JSON."""
    payload: dict = {
        "name": "summarize-article",
        "description": "TL;DR a doc",
        "content": "Summarize:\n{{text}}",
        "input_variables": ["text"],
    }
    payload.update(overrides)
    response = client.post("/prompts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_then_read_prompt(client: TestClient) -> None:
    """POST a prompt, then GET it back — the Sprint 2 demo path."""
    created = _create(client)
    assert created["id"]
    assert created["name"] == "summarize-article"
    assert len(created["versions"]) == 1
    version = created["versions"][0]
    assert version["version_number"] == 1
    assert version["parent_version_id"] is None
    assert version["content"] == "Summarize:\n{{text}}"
    assert version["input_variables"] == ["text"]

    read = client.get("/prompts/summarize-article")
    assert read.status_code == 200
    fetched = read.json()
    assert fetched["id"] == created["id"]
    assert fetched["versions"][0]["content"] == "Summarize:\n{{text}}"


def test_list_prompts_empty(client: TestClient) -> None:
    """An empty registry lists as an empty array, not an error."""
    response = client.get("/prompts")
    assert response.status_code == 200
    assert response.json() == []


def test_list_prompts_returns_summaries_name_ordered(client: TestClient) -> None:
    """List all prompts as lightweight summaries, ordered by name, with version aggregates."""
    _create(client, name="zebra", description="last")
    _create(client, name="alpha", description="first")
    # Give alpha a second version so the aggregate counts are exercised.
    second = client.post("/prompts/alpha/versions", json={"content": "v2", "input_variables": []})
    assert second.status_code == 201, second.text

    response = client.get("/prompts")
    assert response.status_code == 200
    summaries = response.json()

    assert [s["name"] for s in summaries] == ["alpha", "zebra"]

    alpha = summaries[0]
    assert alpha["description"] == "first"
    assert alpha["latest_version"] == 2
    assert alpha["version_count"] == 2
    # The lean summary must not leak version bodies.
    assert "versions" not in alpha
    assert "content" not in alpha

    zebra = summaries[1]
    assert zebra["latest_version"] == 1
    assert zebra["version_count"] == 1


def test_duplicate_name_conflicts(client: TestClient) -> None:
    payload = {"name": "greeting", "content": "Hello", "input_variables": []}
    assert client.post("/prompts", json=payload).status_code == 201
    duplicate = client.post("/prompts", json=payload)
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_get_missing_prompt_returns_404(client: TestClient) -> None:
    assert client.get("/prompts/does-not-exist").status_code == 404


@pytest.mark.parametrize("bad_name", ["bad name!", "", "no/slashes"])
def test_invalid_name_is_rejected(client: TestClient, bad_name: str) -> None:
    response = client.post(
        "/prompts", json={"name": bad_name, "content": "x", "input_variables": []}
    )
    assert response.status_code == 422


def test_version_number_unique_per_prompt(db_session: Session) -> None:
    """The DB itself forbids two versions sharing (prompt_id, version_number)."""
    prompt = Prompt(name="dup-version")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()

    db_session.add(PromptVersion(prompt_id=prompt.id, version_number=1, content="b"))
    with pytest.raises(IntegrityError):
        db_session.flush()


# --------------------------------------------------------------- variable contract


@pytest.mark.parametrize(
    ("content", "input_variables"),
    [
        ("Hi {{name}}", []),  # template uses an undeclared variable
        ("Hi there", ["name"]),  # declares a variable the template never uses
        ("Hi {{name}}", ["name", "name"]),  # duplicate declaration
    ],
)
def test_variable_contract_is_enforced(
    client: TestClient, content: str, input_variables: list[str]
) -> None:
    response = client.post(
        "/prompts",
        json={"name": "contract", "content": content, "input_variables": input_variables},
    )
    assert response.status_code == 422


def test_invalid_output_schema_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/prompts",
        json={
            "name": "schemey",
            "content": "hi",
            "input_variables": [],
            "output_schema": {"type": 123},  # `type` must be a string/array, not int
        },
    )
    assert response.status_code == 422
    assert "output_schema" in response.json()["detail"]


# ------------------------------------------------------------- version history (DoD)


def test_version_history_walkthrough(client: TestClient) -> None:
    """Create a prompt → add 2 more versions → list history → fetch by number."""
    _create(client)  # v1
    for content, ivars in [("v2 {{text}}", ["text"]), ("v3 {{text}} {{tone}}", ["text", "tone"])]:
        added = client.post(
            "/prompts/summarize-article/versions",
            json={"content": content, "input_variables": ivars},
        )
        assert added.status_code == 201, added.text

    history = client.get("/prompts/summarize-article/versions")
    assert history.status_code == 200
    versions = history.json()
    assert [v["version_number"] for v in versions] == [1, 2, 3]
    # lineage is linear: each version's parent is the previous one
    assert versions[0]["parent_version_id"] is None
    assert versions[1]["parent_version_id"] == versions[0]["id"]
    assert versions[2]["parent_version_id"] == versions[1]["id"]

    v2 = client.get("/prompts/summarize-article/versions/2")
    assert v2.status_code == 200
    assert v2.json()["content"] == "v2 {{text}}"

    assert client.get("/prompts/summarize-article/versions/99").status_code == 404


def test_add_version_to_missing_prompt_404(client: TestClient) -> None:
    response = client.post("/prompts/ghost/versions", json={"content": "x", "input_variables": []})
    assert response.status_code == 404


# ------------------------------------------------------------------------- render


def test_render_succeeds_with_valid_variables(client: TestClient) -> None:
    _create(
        client,
        name="render-me",
        content="Hello {{name}}, welcome to {{place}}.",
        input_variables=["name", "place"],
        model_settings={"model": "claude-opus-4-8", "temperature": 0.2},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )
    response = client.post(
        "/prompts/render-me/versions/1/render",
        json={"variables": {"name": "Ada", "place": "PromptForge"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prompt"] == "Hello Ada, welcome to PromptForge."
    assert body["model_settings"] == {"model": "claude-opus-4-8", "temperature": 0.2}
    assert body["output_schema"]["properties"]["reply"]["type"] == "string"


def test_render_fails_loudly_on_missing_variable(client: TestClient) -> None:
    _create(client, name="needs-vars", content="Hi {{a}} {{b}}", input_variables=["a", "b"])
    response = client.post("/prompts/needs-vars/versions/1/render", json={"variables": {"a": "x"}})
    assert response.status_code == 422
    assert "missing variables" in response.json()["detail"]


def test_render_rejects_unexpected_variable(client: TestClient) -> None:
    _create(client, name="strict", content="Hi {{a}}", input_variables=["a"])
    response = client.post(
        "/prompts/strict/versions/1/render", json={"variables": {"a": "x", "b": "y"}}
    )
    assert response.status_code == 422
    assert "unexpected variables" in response.json()["detail"]


def test_render_does_not_reinterpret_values(client: TestClient) -> None:
    """A value that looks like a placeholder is inserted literally (no SSTI)."""
    _create(client, name="safe", content="value: {{a}}", input_variables=["a"])
    response = client.post(
        "/prompts/safe/versions/1/render", json={"variables": {"a": "{{b}} ${injected}"}}
    )
    assert response.status_code == 200
    assert response.json()["prompt"] == "value: {{b}} ${injected}"


# -------------------------------------------------------------------------- labels


def test_label_set_resolve_and_move(client: TestClient) -> None:
    """Set a label, resolve it, then move it to a new version (a deploy)."""
    _create(client, name="deployable", content="v1", input_variables=[])
    client.post("/prompts/deployable/versions", json={"content": "v2", "input_variables": []})

    set_v1 = client.put("/prompts/deployable/labels/staging", json={"version_number": 1})
    assert set_v1.status_code == 200
    assert set_v1.json()["version"]["version_number"] == 1

    resolved = client.get("/prompts/deployable/labels/staging")
    assert resolved.status_code == 200
    assert resolved.json()["version_number"] == 1

    # move the pointer to v2 — same label, no new row, this is the deploy primitive.
    # The move's *response body* (not just a later GET) must reflect v2: this guards
    # the in-memory-relationship fix — setting only the FK left .version stale.
    set_v2 = client.put("/prompts/deployable/labels/staging", json={"version_number": 2})
    assert set_v2.status_code == 200
    assert set_v2.json()["version"]["version_number"] == 2
    assert client.get("/prompts/deployable/labels/staging").json()["version_number"] == 2


def test_resolve_missing_label_404(client: TestClient) -> None:
    _create(client, name="nolabels", content="x", input_variables=[])
    assert client.get("/prompts/nolabels/labels/staging").status_code == 404


# ----------------------------------------------------------------- render by label


def test_render_by_label_returns_pointed_version(client: TestClient) -> None:
    """POST /prompts/{name}/render renders whatever the label points at (the SDK call)."""
    _create(client, name="floating", content="v1 {{x}}", input_variables=["x"])
    client.post(
        "/prompts/floating/versions", json={"content": "v2 {{x}}", "input_variables": ["x"]}
    )
    client.put("/prompts/floating/labels/staging", json={"version_number": 1})

    response = client.post(
        "/prompts/floating/render", json={"label": "staging", "variables": {"x": "hi"}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["prompt"] == "v1 hi"

    # Move the label (a deploy) — the same call now floats to v2 with no caller change.
    client.put("/prompts/floating/labels/staging", json={"version_number": 2})
    moved = client.post(
        "/prompts/floating/render", json={"label": "staging", "variables": {"x": "hi"}}
    )
    assert moved.json()["prompt"] == "v2 hi"


def test_render_by_label_carries_model_config(client: TestClient) -> None:
    _create(
        client,
        name="configured",
        content="Hello {{name}}",
        input_variables=["name"],
        model_settings={"model": "claude-opus-4-8", "temperature": 0.2},
    )
    client.put("/prompts/configured/labels/staging", json={"version_number": 1})
    body = client.post(
        "/prompts/configured/render", json={"label": "staging", "variables": {"name": "Ada"}}
    ).json()
    assert body["prompt"] == "Hello Ada"
    assert body["model_settings"] == {"model": "claude-opus-4-8", "temperature": 0.2}


def test_render_by_label_unknown_label_404(client: TestClient) -> None:
    _create(client, name="unlabeled", content="x", input_variables=[])
    response = client.post("/prompts/unlabeled/render", json={"label": "staging", "variables": {}})
    assert response.status_code == 404


def test_render_by_label_wrong_variables_422(client: TestClient) -> None:
    _create(client, name="needsvar", content="Hi {{a}}", input_variables=["a"])
    client.put("/prompts/needsvar/labels/staging", json={"version_number": 1})
    response = client.post("/prompts/needsvar/render", json={"label": "staging", "variables": {}})
    assert response.status_code == 422
    assert "missing variables" in response.json()["detail"]


def test_set_label_to_missing_version_404(client: TestClient) -> None:
    _create(client, name="onlyv1", content="x", input_variables=[])
    response = client.put("/prompts/onlyv1/labels/staging", json={"version_number": 99})
    assert response.status_code == 404
