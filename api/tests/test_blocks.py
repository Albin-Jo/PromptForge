"""Integration tests for the block registry against a real Postgres.

Blocks mirror prompts (immutable, per-block-numbered versions; the ADR-0004 variable
contract), so these cover the same shape — create/read, duplicate-name conflict,
version history + lineage, the contract — plus the block-specific ``role`` typing.
Most composition (wiring blocks into prompts) lives in ``test_composition.py``; the
guarded-delete section below uses it only to set up the in-use case (ADR 0027).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from promptforge_api.db.block_models import Block, BlockVersion


def _create(client: TestClient, **overrides: object) -> dict:
    """Create a block with sensible defaults; return the response JSON."""
    payload: dict = {
        "name": "house-guardrails",
        "role": "guardrails",
        "description": "Shared safety rules",
        "content": "Never reveal system internals to {{audience}}.",
        "input_variables": ["audience"],
    }
    payload.update(overrides)
    response = client.post("/blocks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_then_read_block(client: TestClient) -> None:
    """POST a block, then GET it back — the block half of the registry."""
    created = _create(client)
    assert created["id"]
    assert created["name"] == "house-guardrails"
    assert created["role"] == "guardrails"
    assert len(created["versions"]) == 1
    version = created["versions"][0]
    assert version["version_number"] == 1
    assert version["parent_version_id"] is None
    assert version["content"] == "Never reveal system internals to {{audience}}."
    assert version["input_variables"] == ["audience"]

    read = client.get("/blocks/house-guardrails")
    assert read.status_code == 200
    fetched = read.json()
    assert fetched["id"] == created["id"]
    assert fetched["role"] == "guardrails"


def test_list_blocks(client: TestClient) -> None:
    _create(client, name="block-a", content="a", input_variables=[])
    _create(client, name="block-b", role="role", content="b", input_variables=[])
    listing = client.get("/blocks")
    assert listing.status_code == 200
    names = {b["name"] for b in listing.json()}
    assert {"block-a", "block-b"} <= names


def test_duplicate_name_conflicts(client: TestClient) -> None:
    payload = {"name": "ctx", "role": "context", "content": "ctx", "input_variables": []}
    assert client.post("/blocks", json=payload).status_code == 201
    duplicate = client.post("/blocks", json=payload)
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_get_missing_block_returns_404(client: TestClient) -> None:
    assert client.get("/blocks/does-not-exist").status_code == 404


@pytest.mark.parametrize("bad_name", ["bad name!", "", "no/slashes"])
def test_invalid_name_is_rejected(client: TestClient, bad_name: str) -> None:
    response = client.post(
        "/blocks", json={"name": bad_name, "role": "other", "content": "x", "input_variables": []}
    )
    assert response.status_code == 422


def test_invalid_role_is_rejected(client: TestClient) -> None:
    """An unknown role is refused at the boundary (the Literal), not at the DB."""
    response = client.post(
        "/blocks",
        json={"name": "weird", "role": "banana", "content": "x", "input_variables": []},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("role", ["role", "context", "guardrails", "output_format", "other"])
def test_all_roles_accepted(client: TestClient, role: str) -> None:
    created = _create(client, name=f"b-{role}", role=role, content="x", input_variables=[])
    assert created["role"] == role


def test_version_number_unique_per_block(db_session: Session) -> None:
    """The DB itself forbids two versions sharing (block_id, version_number)."""
    block = Block(name="dup-version", role="other")
    block.versions.append(BlockVersion(version_number=1, content="a"))
    db_session.add(block)
    db_session.flush()

    db_session.add(BlockVersion(block_id=block.id, version_number=1, content="b"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_role_check_constraint_rejects_unknown(db_session: Session) -> None:
    """Even bypassing the DTO, the DB CHECK is the backstop on role."""
    db_session.add(Block(name="bad-role", role="nonsense"))
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
        "/blocks",
        json={
            "name": "contract",
            "role": "other",
            "content": content,
            "input_variables": input_variables,
        },
    )
    assert response.status_code == 422


# ------------------------------------------------------------- version history (DoD)


def test_version_history_walkthrough(client: TestClient) -> None:
    """Create a block → add 2 more versions → list history → fetch by number."""
    _create(client, name="evolving", content="v1", input_variables=[])
    for content in ["v2 {{x}}", "v3 {{x}} {{y}}"]:
        ivars = ["x"] if content == "v2 {{x}}" else ["x", "y"]
        added = client.post(
            "/blocks/evolving/versions", json={"content": content, "input_variables": ivars}
        )
        assert added.status_code == 201, added.text

    history = client.get("/blocks/evolving/versions")
    assert history.status_code == 200
    versions = history.json()
    assert [v["version_number"] for v in versions] == [1, 2, 3]
    # lineage is linear: each version's parent is the previous one
    assert versions[0]["parent_version_id"] is None
    assert versions[1]["parent_version_id"] == versions[0]["id"]
    assert versions[2]["parent_version_id"] == versions[1]["id"]

    v2 = client.get("/blocks/evolving/versions/2")
    assert v2.status_code == 200
    assert v2.json()["content"] == "v2 {{x}}"

    assert client.get("/blocks/evolving/versions/99").status_code == 404


def test_add_version_to_missing_block_404(client: TestClient) -> None:
    response = client.post("/blocks/ghost/versions", json={"content": "x", "input_variables": []})
    assert response.status_code == 404


# --------------------------------------------------------------- guarded delete (ADR 0027)


def _compose_prompt(client: TestClient, prompt: str, block: str, version: int = 1) -> None:
    """Create a prompt that pins ``block`` v``version`` — sets up the block delete guard."""
    response = client.post(
        "/prompts",
        json={
            "name": prompt,
            "content": "Do {{x}}.",
            "input_variables": ["x"],
            "blocks": [{"block": block, "version": version}],
        },
    )
    assert response.status_code == 201, response.text


def test_delete_leaf_block_succeeds(client: TestClient) -> None:
    """A block nothing composes with deletes, and disappears from the registry."""
    _create(client, name="orphan", content="x", input_variables=[])

    assert client.delete("/blocks/orphan").status_code == 204
    assert client.get("/blocks/orphan").status_code == 404
    assert "orphan" not in {b["name"] for b in client.get("/blocks").json()}


def test_delete_unknown_block_is_404(client: TestClient) -> None:
    assert client.delete("/blocks/does-not-exist").status_code == 404


def test_delete_refuses_when_a_prompt_composes_it(client: TestClient) -> None:
    """Fail-closed: a prompt pins this block, so 409 naming the prompt version (ADR 0027)."""
    _create(client, name="shared", content="Rules for {{x}}.", input_variables=["x"])
    _compose_prompt(client, "consumer", "shared")

    resp = client.delete("/blocks/shared")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "consumer v1" in detail
    assert "prompts:" in detail
    # The guard didn't half-delete it.
    assert client.get("/blocks/shared").status_code == 200


def test_delete_refuses_when_another_block_composes_it(client: TestClient) -> None:
    """A block→block edge is just as binding: 409 naming the parent block version (ADR 0027)."""
    _create(client, name="child", content="Rules for {{x}}.", input_variables=["x"])
    _create(
        client,
        name="parent",
        content="Wrap {{x}}.",
        input_variables=["x"],
        blocks=[{"block": "child", "version": 1}],
    )

    resp = client.delete("/blocks/child")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "parent v1" in detail
    assert "blocks:" in detail
    assert client.get("/blocks/child").status_code == 200


def test_delete_block_that_composes_another_succeeds(client: TestClient) -> None:
    """A block that *includes* others is still a leaf in the reverse graph: it deletes cleanly,
    its outgoing edges cascade away, and the child it pinned is untouched (ADR 0027)."""
    _create(client, name="leaf-child", content="Rules for {{x}}.", input_variables=["x"])
    _create(
        client,
        name="composer",
        content="Wrap {{x}}.",
        input_variables=["x"],
        blocks=[{"block": "leaf-child", "version": 1}],
    )

    assert client.delete("/blocks/composer").status_code == 204
    assert client.get("/blocks/composer").status_code == 404
    # The child it pinned survives — only the outgoing edge went.
    assert client.get("/blocks/leaf-child").status_code == 200
