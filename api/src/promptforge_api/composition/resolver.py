"""Render-time composition resolution — assemble a composed prompt from its blocks.

This is the "gather → order → final prompt" step (Sprint 10). It works on an
already-loaded :class:`BlockSubgraph` (the repository does the I/O), so the assembly
logic itself is pure and unit-testable. Two operations:

- :func:`collect_variables` — the union of every included block's declared variables,
  used at create time to validate the composed version's contract.
- :func:`resolve` — produce the finished prompt text. Blocks are filled in **topological
  order** (a block is rendered only after the blocks it includes), then concatenated in
  **position order**: each container emits its children (in order) followed by its own
  content. Variable values are filled through the same mustache engine as a plain
  prompt — a block uses its subset of the provided variables; extras are ignored.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from promptforge_api.composition.graph import topological_sort
from promptforge_api.templating import render_template

# Composed sections are separated by a blank line — the natural seam between prompt
# parts (guardrails, then context, then the task). Empty parts are dropped so a
# container with no own content (a pure wrapper) doesn't leave a trailing gap.
_SECTION_SEP = "\n\n"


@dataclass(frozen=True)
class BlockNode:
    """One block version in a loaded composition subgraph."""

    block_version_id: uuid.UUID
    block_id: uuid.UUID
    block_name: str
    content: str
    input_variables: tuple[str, ...]
    # Child block versions this one includes, in composition (position) order.
    children: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class BlockSubgraph:
    """Every block version transitively reachable from a composition's direct blocks."""

    nodes: Mapping[uuid.UUID, BlockNode]


def collect_variables(subgraph: BlockSubgraph) -> set[str]:
    """The union of declared variables across every block in the subgraph."""
    variables: set[str] = set()
    for node in subgraph.nodes.values():
        variables.update(node.input_variables)
    return variables


def _join(parts: Sequence[str]) -> str:
    """Concatenate non-empty parts with a blank-line separator."""
    return _SECTION_SEP.join(part for part in parts if part)


def resolve(
    own_content: str,
    top_block_ids: Sequence[uuid.UUID],
    subgraph: BlockSubgraph,
    variables: Mapping[str, str],
) -> str:
    """Assemble the finished prompt: included blocks (ordered) then the own content.

    Fills a memo of each block version's fully-resolved text in topological order, so a
    parent always finds its children already resolved, then assembles the container from
    its top-level blocks (in position order) followed by its own rendered content.
    """
    adjacency = {bv_id: list(node.children) for bv_id, node in subgraph.nodes.items()}
    resolved: dict[uuid.UUID, str] = {}
    for bv_id in topological_sort(adjacency):
        node = subgraph.nodes[bv_id]
        parts = [resolved[child] for child in node.children]
        parts.append(render_template(node.content, variables))
        resolved[bv_id] = _join(parts)

    top = [resolved[bv_id] for bv_id in top_block_ids]
    top.append(render_template(own_content, variables))
    return _join(top)
