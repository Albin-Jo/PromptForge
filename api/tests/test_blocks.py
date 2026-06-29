"""Integration tests for the block registry against a real Postgres.

Blocks mirror prompts (immutable, per-block-numbered versions; the ADR-0004 variable
contract), so these cover the same shape — create/read, duplicate-name conflict,
version history + lineage, the contract — plus the block-specific ``role`` typing.
Composition (wiring blocks into prompts) is a later task and is not exercised here.
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
