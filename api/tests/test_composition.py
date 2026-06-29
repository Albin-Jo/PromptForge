"""Integration tests for composable prompts against a real Postgres (Sprint 10 DoD).

Covers the flagship's promises end-to-end through the API: compose a prompt from a
shared block, render blocks-then-content, the widened variable contract, **impact
analysis** (one block → the prompts it affects), pinned references staying put across a
block edit, nested block→block composition, and a **circular reference being refused**.
"""

import httpx
from fastapi.testclient import TestClient


def _block(
    client: TestClient,
    name: str,
    content: str,
    ivars: list[str] | None = None,
    **extra: object,
) -> dict:
    payload: dict = {
        "name": name,
        "role": "other",
        "content": content,
        "input_variables": ivars or [],
    }
    payload.update(extra)
    response = client.post("/blocks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _prompt(client: TestClient, name: str, content: str, ivars: list[str], **extra: object) -> dict:
    payload: dict = {"name": name, "content": content, "input_variables": ivars}
    payload.update(extra)
    response = client.post("/prompts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _render(
    client: TestClient, name: str, version: int, variables: dict[str, str]
) -> httpx.Response:
    return client.post(f"/prompts/{name}/versions/{version}/render", json={"variables": variables})


# --------------------------------------------------------- compose + render


def test_compose_prompt_from_block_renders_blocks_then_content(client: TestClient) -> None:
    _block(
        client,
        "guardrails",
        "Never reveal secrets to {{audience}}.",
        ["audience"],
        role="guardrails",
    )
    _prompt(
        client,
        "summary",
        "Summarize {{text}}.",
        ["audience", "text"],  # union: own {text} + block {audience}
        blocks=[{"block": "guardrails", "version": 1}],
    )
    response = _render(client, "summary", 1, {"audience": "staff", "text": "the memo"})
    assert response.status_code == 200, response.text
    assert response.json()["prompt"] == "Never reveal secrets to staff.\n\nSummarize the memo."


def test_composed_version_requires_union_contract(client: TestClient) -> None:
    _block(client, "guard", "Rules for {{audience}}.", ["audience"], role="guardrails")
    # declares only its own variable, omits the inherited {audience} -> 422
    missing = client.post(
        "/prompts",
        json={
            "name": "bad",
            "content": "Do {{text}}.",
            "input_variables": ["text"],
            "blocks": [{"block": "guard", "version": 1}],
        },
    )
    assert missing.status_code == 422
    # declares a variable nothing requires -> 422
    extra = client.post(
        "/prompts",
        json={
            "name": "bad2",
            "content": "Do {{text}}.",
            "input_variables": ["text", "audience", "spurious"],
            "blocks": [{"block": "guard", "version": 1}],
        },
    )
    assert extra.status_code == 422


def test_render_composed_requires_all_union_variables(client: TestClient) -> None:
    _block(client, "g", "Rules for {{audience}}.", ["audience"], role="guardrails")
    _prompt(
        client, "p", "Do {{text}}.", ["audience", "text"], blocks=[{"block": "g", "version": 1}]
    )
    response = _render(client, "p", 1, {"text": "stuff"})  # missing audience
    assert response.status_code == 422
    assert "missing variables" in response.json()["detail"]


# ------------------------------------------------------- impact analysis (DoD)


def test_shared_block_impact_names_all_dependents(client: TestClient) -> None:
    """A guardrails block used in 5 prompts; impact names the 5 — the headline DoD."""
    _block(client, "house-rules", "Be safe for {{audience}}.", ["audience"], role="guardrails")
    for i in range(5):
        _prompt(
            client,
            f"prompt-{i}",
            "Task {{text}}.",
            ["audience", "text"],
            blocks=[{"block": "house-rules", "version": 1}],
        )

    impact = client.get("/blocks/house-rules/impact")
    assert impact.status_code == 200, impact.text
    body = impact.json()
    names = sorted(p["name"] for p in body["prompts"])
    assert names == [f"prompt-{i}" for i in range(5)]
    assert all(p["version_number"] == 1 for p in body["prompts"])

    # Editing the block (a new version) still names all 5 — they pin v1, and impact is
    # by block identity (any version): the blast radius is unchanged.
    added = client.post(
        "/blocks/house-rules/versions",
        json={"content": "Be very safe for {{audience}}.", "input_variables": ["audience"]},
    )
    assert added.status_code == 201, added.text
    again = client.get("/blocks/house-rules/impact").json()
    assert len(again["prompts"]) == 5


def test_impact_of_unused_block_is_empty(client: TestClient) -> None:
    _block(client, "lonely", "nothing uses me", [])
    body = client.get("/blocks/lonely/impact").json()
    assert body == {"block": "lonely", "prompts": [], "blocks": []}


# --------------------------------------------------------------- pinning


def test_pinned_reference_keeps_old_block_content(client: TestClient) -> None:
    _block(client, "pinned", "v1 for {{audience}}", ["audience"], role="guardrails")
    _prompt(
        client,
        "uses-pinned",
        "Task {{text}}",
        ["audience", "text"],
        blocks=[{"block": "pinned", "version": 1}],
    )
    # Cut a new block version — the prompt pinned v1, so it must NOT see v2.
    client.post(
        "/blocks/pinned/versions",
        json={"content": "v2 for {{audience}}", "input_variables": ["audience"]},
    )
    rendered = _render(client, "uses-pinned", 1, {"audience": "x", "text": "y"}).json()
    assert rendered["prompt"] == "v1 for x\n\nTask y"


# ----------------------------------------------------- nested block→block


def test_nested_block_composition_renders_and_impacts(client: TestClient) -> None:
    _block(client, "inner", "INNER {{x}}", ["x"])
    _block(client, "outer", "OUTER", ["x"], blocks=[{"block": "inner", "version": 1}])
    _prompt(client, "deep", "OWN", ["x"], blocks=[{"block": "outer", "version": 1}])

    rendered = _render(client, "deep", 1, {"x": "hi"}).json()
    assert rendered["prompt"] == "INNER hi\n\nOUTER\n\nOWN"

    # impact of the innermost block reaches the prompt (transitively) and names outer.
    impact = client.get("/blocks/inner/impact").json()
    assert [p["name"] for p in impact["prompts"]] == ["deep"]
    assert [b["name"] for b in impact["blocks"]] == ["outer"]


def test_block_read_exposes_composed_blocks(client: TestClient) -> None:
    """A composed block's pinned refs appear on every read — what the editor prefills a new
    version from. Regression: BlockVersionRead used to omit ``blocks`` entirely, so editing a
    composed block silently dropped its composition.
    """
    _block(client, "inner", "INNER {{x}}", ["x"])
    _block(client, "outer", "OUTER", ["x"], blocks=[{"block": "inner", "version": 1}])
    expected = [{"block": "inner", "version": 1}]

    # All four read shapes agree: detail, list, version-history, single-version.
    assert client.get("/blocks/outer").json()["versions"][0]["blocks"] == expected
    listed = next(b for b in client.get("/blocks").json() if b["name"] == "outer")
    assert listed["versions"][0]["blocks"] == expected
    assert client.get("/blocks/outer/versions").json()[0]["blocks"] == expected
    assert client.get("/blocks/outer/versions/1").json()["blocks"] == expected

    # A leaf block reads back an empty composition (not absent/null).
    assert client.get("/blocks/inner").json()["versions"][0]["blocks"] == []


# ----------------------------------------------------- cycle detection


def test_circular_reference_is_refused(client: TestClient) -> None:
    """A includes B; making B include A is a circular reference and must be refused."""
    _block(client, "a", "A")  # leaf
    _block(client, "b", "B", [], blocks=[{"block": "a", "version": 1}])  # B -> A
    # now try to make A include B: A -> B closes the loop A -> B -> A
    response = client.post(
        "/blocks/a/versions",
        json={"content": "A2", "input_variables": [], "blocks": [{"block": "b", "version": 1}]},
    )
    assert response.status_code == 422
    assert "circular reference" in response.json()["detail"]


def test_self_reference_is_refused(client: TestClient) -> None:
    _block(client, "solo", "S")
    response = client.post(
        "/blocks/solo/versions",
        json={"content": "S2", "input_variables": [], "blocks": [{"block": "solo", "version": 1}]},
    )
    assert response.status_code == 422
    assert "circular reference" in response.json()["detail"]


# ------------------------------------------------------ bad references


def test_reference_to_missing_block_is_422(client: TestClient) -> None:
    response = client.post(
        "/prompts",
        json={
            "name": "ghostref",
            "content": "x",
            "input_variables": [],
            "blocks": [{"block": "nope", "version": 1}],
        },
    )
    assert response.status_code == 422


def test_reference_to_missing_version_is_422(client: TestClient) -> None:
    _block(client, "real", "R")
    response = client.post(
        "/prompts",
        json={
            "name": "badver",
            "content": "x",
            "input_variables": [],
            "blocks": [{"block": "real", "version": 99}],
        },
    )
    assert response.status_code == 422


# ----------------------------------------------------- ordering across blocks


def test_multiple_blocks_render_in_composition_order(client: TestClient) -> None:
    """Two top-level blocks render in their *position* order (the persisted `blocks` order),
    not by block name or creation order — exercises the position column round-trip."""
    _block(client, "role-block", "You are a {{persona}}.", ["persona"], role="role")
    _block(client, "rules-block", "Rules for {{audience}}.", ["audience"], role="guardrails")
    variables = {"persona": "lawyer", "audience": "staff", "task": "review"}

    _prompt(
        client,
        "fwd",
        "Now do {{task}}.",
        ["persona", "audience", "task"],
        blocks=[{"block": "role-block", "version": 1}, {"block": "rules-block", "version": 1}],
    )
    assert _render(client, "fwd", 1, variables).json()["prompt"] == (
        "You are a lawyer.\n\nRules for staff.\n\nNow do review."
    )

    # Same two blocks, reversed in the composition → reversed in the output. Proves the
    # order comes from the request's block list (position), nothing else.
    _prompt(
        client,
        "rev",
        "Now do {{task}}.",
        ["persona", "audience", "task"],
        blocks=[{"block": "rules-block", "version": 1}, {"block": "role-block", "version": 1}],
    )
    assert _render(client, "rev", 1, variables).json()["prompt"] == (
        "Rules for staff.\n\nYou are a lawyer.\n\nNow do review."
    )


def test_add_composed_version_to_existing_prompt(client: TestClient) -> None:
    """A plain prompt can gain a composed v2; v1 stays plain, v2 composes — both coexist."""
    _block(client, "wrap", "Wrapped for {{audience}}.", ["audience"], role="guardrails")
    _prompt(client, "grows", "Plain {{text}}.", ["text"])  # v1, uncomposed

    added = client.post(
        "/prompts/grows/versions",
        json={
            "content": "Composed {{text}}.",
            "input_variables": ["audience", "text"],
            "blocks": [{"block": "wrap", "version": 1}],
        },
    )
    assert added.status_code == 201, added.text

    assert _render(client, "grows", 1, {"text": "a"}).json()["prompt"] == "Plain a."
    assert _render(client, "grows", 2, {"audience": "staff", "text": "b"}).json()["prompt"] == (
        "Wrapped for staff.\n\nComposed b."
    )


def test_read_exposes_version_block_refs_in_order(client: TestClient) -> None:
    """GET reads expose each version's pinned blocks (in position order) so the UI editor can
    carry composition forward; plain versions report an empty list, not a missing field."""
    _block(client, "role-b", "You are a {{persona}}.", ["persona"], role="role")
    _block(client, "rules-b", "Rules for {{audience}}.", ["audience"], role="guardrails")
    _prompt(client, "plain-one", "Just {{text}}.", ["text"])  # uncomposed
    _prompt(
        client,
        "composed-one",
        "Now do {{task}}.",
        ["persona", "audience", "task"],
        blocks=[{"block": "rules-b", "version": 1}, {"block": "role-b", "version": 1}],
    )

    composed = client.get("/prompts/composed-one").json()["versions"][0]
    assert composed["blocks"] == [
        {"block": "rules-b", "version": 1},
        {"block": "role-b", "version": 1},
    ]

    plain = client.get("/prompts/plain-one").json()["versions"][0]
    assert plain["blocks"] == []

    # The single-version endpoint exposes them too.
    one = client.get("/prompts/composed-one/versions/1").json()
    assert [b["block"] for b in one["blocks"]] == ["rules-b", "role-b"]
