"""Unit tests for composition assembly (no DB) — over hand-built subgraphs.

Checks the "gather → order → concat" contract: blocks render in dependency order and
concatenate as children-then-own-content, separated by a blank line, with empty parts
dropped. The graph ordering itself is tested in test_composition_graph; here we test
that resolution *uses* that order to produce the right text.
"""

import uuid

from promptforge_api.composition.resolver import (
    BlockNode,
    BlockSubgraph,
    collect_variables,
    resolve,
)


def _node(
    content: str,
    *,
    variables: tuple[str, ...] = (),
    children: tuple[uuid.UUID, ...] = (),
) -> BlockNode:
    bv_id = uuid.uuid4()
    return BlockNode(
        block_version_id=bv_id,
        block_id=uuid.uuid4(),
        block_name="b",
        content=content,
        input_variables=variables,
        children=children,
    )


def test_single_block_then_own_content() -> None:
    block = _node("Guardrails for {{audience}}.", variables=("audience",))
    subgraph = BlockSubgraph(nodes={block.block_version_id: block})
    text = resolve(
        "Summarize {{text}}.",
        [block.block_version_id],
        subgraph,
        {
            "audience": "staff",
            "text": "the memo",
        },
    )
    assert text == "Guardrails for staff.\n\nSummarize the memo."


def test_nested_blocks_resolve_inner_first() -> None:
    inner = _node("INNER")
    outer = _node("OUTER", children=(inner.block_version_id,))
    subgraph = BlockSubgraph(nodes={inner.block_version_id: inner, outer.block_version_id: outer})
    # prompt includes outer; outer includes inner. Assembly: inner, outer, own.
    text = resolve("OWN", [outer.block_version_id], subgraph, {})
    assert text == "INNER\n\nOUTER\n\nOWN"


def test_multiple_top_blocks_keep_position_order() -> None:
    first = _node("FIRST")
    second = _node("SECOND")
    subgraph = BlockSubgraph(nodes={first.block_version_id: first, second.block_version_id: second})
    text = resolve("", [first.block_version_id, second.block_version_id], subgraph, {})
    assert text == "FIRST\n\nSECOND"


def test_empty_parts_are_dropped() -> None:
    empty = _node("")  # a pure wrapper with no own text
    subgraph = BlockSubgraph(nodes={empty.block_version_id: empty})
    # empty block + empty own content collapse to nothing, no stray separators
    assert resolve("", [empty.block_version_id], subgraph, {}) == ""
    # own content survives on its own
    assert resolve("just own", [empty.block_version_id], subgraph, {}) == "just own"


def test_values_are_not_reinterpreted() -> None:
    """A value that looks like a placeholder is inserted literally (no SSTI), as in plain render."""
    block = _node("value: {{a}}", variables=("a",))
    subgraph = BlockSubgraph(nodes={block.block_version_id: block})
    text = resolve("", [block.block_version_id], subgraph, {"a": "{{b}} ${x}"})
    assert text == "value: {{b}} ${x}"


def test_collect_variables_unions_across_blocks() -> None:
    a = _node("{{x}}", variables=("x",))
    b = _node("{{y}} {{z}}", variables=("y", "z"))
    subgraph = BlockSubgraph(nodes={a.block_version_id: a, b.block_version_id: b})
    assert collect_variables(subgraph) == {"x", "y", "z"}
