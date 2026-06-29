"""Create-time composition: pin references, compute the variable union, guard cycles.

The prompt and block services share these helpers so the composition rules live in one
place. None of this persists the composition edges — the service does that once the
container version has an id; this just validates that a composition is well-formed:

- :func:`pin_composition` resolves each reference to an exact block version (ADR 0015)
  and gathers the variables the composition inherits from the blocks it includes.
- :func:`assert_acyclic` refuses a block whose references would close a cycle in the
  block-identity graph (the only place a cycle can form — a prompt is always a sink).
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from promptforge_api.composition.graph import CompositionCycleError, find_cycle
from promptforge_api.composition.resolver import collect_variables
from promptforge_api.repositories.composition import CompositionRepository


@dataclass(frozen=True)
class BlockRef:
    """A pinned reference to an exact block version, by block name + version number."""

    block: str
    version: int


class BlockReferenceNotFoundError(Exception):
    """Raised when a composition references a block version that doesn't exist."""

    def __init__(self, block: str, version: int) -> None:
        super().__init__(f"referenced block '{block}' has no version {version}")
        self.block = block
        self.version = version


@dataclass(frozen=True)
class PinnedComposition:
    """The result of resolving a list of references against the registry."""

    # Direct block versions, in composition (position) order — what gets persisted.
    block_version_ids: list[uuid.UUID]
    # The block identities of those direct references — what the cycle guard needs.
    direct_block_ids: list[uuid.UUID]
    # Variables the composition inherits from every block it (transitively) includes.
    inherited_variables: set[str]


def pin_composition(repo: CompositionRepository, refs: Iterable[BlockRef]) -> PinnedComposition:
    """Resolve each reference to an exact block version and gather inherited variables."""
    block_version_ids: list[uuid.UUID] = []
    for ref in refs:
        version = repo.resolve_block_ref(ref.block, ref.version)
        if version is None:
            raise BlockReferenceNotFoundError(ref.block, ref.version)
        block_version_ids.append(version.id)

    subgraph = repo.load_block_subgraph(block_version_ids)
    direct_block_ids = [subgraph.nodes[bv_id].block_id for bv_id in block_version_ids]
    inherited = collect_variables(subgraph)
    return PinnedComposition(block_version_ids, direct_block_ids, inherited)


def assert_acyclic(
    repo: CompositionRepository,
    new_block_id: uuid.UUID,
    new_block_name: str,
    direct_block_ids: Sequence[uuid.UUID],
) -> None:
    """Refuse a block whose references would create a circular reference (ADR 0015).

    Builds the existing block-identity graph, adds the prospective edges from this block
    to the blocks it would include, and looks for a cycle. The existing graph is acyclic
    (every prior create passed this same guard), so any cycle found must run through this
    block — we surface it as a named path for a clear 422.
    """
    adjacency = {node: set(children) for node, children in repo.load_identity_adjacency().items()}
    adjacency.setdefault(new_block_id, set()).update(direct_block_ids)

    cycle = find_cycle(adjacency)
    if cycle is None:
        return

    names = repo.all_block_names()
    names[new_block_id] = new_block_name
    raise CompositionCycleError([names.get(block_id, str(block_id)) for block_id in cycle])
