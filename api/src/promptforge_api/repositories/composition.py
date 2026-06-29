"""Data access for composition — the edge tables and the graph queries over them.

No business rules; the service decides what a composition *means* (cycle policy,
variable union). This module knows how to: pin a reference (resolve a block name +
number to an exact version), persist edges, load the subgraph a render needs, expose
the block-identity adjacency the cycle guard checks, and walk the **reverse** graph for
impact analysis. The reverse walk is exact and version-level (it follows pinned edges),
which is well-defined because the version graph is acyclic by construction (ADR 0015).
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from promptforge_api.composition.resolver import BlockNode, BlockSubgraph
from promptforge_api.db.block_models import Block, BlockVersion
from promptforge_api.db.composition_models import BlockVersionBlock, PromptVersionBlock
from promptforge_api.db.models import Prompt, PromptVersion


class CompositionRepository:
    """Persistence + graph queries for prompt/block composition."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --------------------------------------------------------------- pinning
    def resolve_block_ref(self, block_name: str, version_number: int) -> BlockVersion | None:
        """Resolve a pinned reference (block name + version) to its exact BlockVersion."""
        stmt = (
            select(BlockVersion)
            .join(Block, BlockVersion.block_id == Block.id)
            .where(Block.name == block_name, BlockVersion.version_number == version_number)
        )
        return self._session.scalars(stmt).one_or_none()

    # -------------------------------------------------------------- persist
    def add_prompt_block(
        self, prompt_version_id: uuid.UUID, block_version_id: uuid.UUID, position: int
    ) -> None:
        """Stage one prompt→block composition edge for insert."""
        self._session.add(
            PromptVersionBlock(
                prompt_version_id=prompt_version_id,
                block_version_id=block_version_id,
                position=position,
            )
        )

    def add_block_block(
        self, parent_block_version_id: uuid.UUID, child_block_version_id: uuid.UUID, position: int
    ) -> None:
        """Stage one block→block composition edge for insert."""
        self._session.add(
            BlockVersionBlock(
                parent_block_version_id=parent_block_version_id,
                child_block_version_id=child_block_version_id,
                position=position,
            )
        )

    # ------------------------------------------------------------- read-model
    def block_refs_for_prompt_versions(
        self, prompt_version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, int]]]:
        """Pinned (block name, version number) refs per prompt version, in position order.

        One query for the whole set (no N+1 across a prompt's history): the caller passes
        every version id and gets back a map it can attach to each version's read DTO.
        Versions with no composition simply don't appear in the map.
        """
        if not prompt_version_ids:
            return {}
        stmt = (
            select(
                PromptVersionBlock.prompt_version_id,
                Block.name,
                BlockVersion.version_number,
            )
            .join(BlockVersion, PromptVersionBlock.block_version_id == BlockVersion.id)
            .join(Block, BlockVersion.block_id == Block.id)
            .where(PromptVersionBlock.prompt_version_id.in_(prompt_version_ids))
            .order_by(PromptVersionBlock.prompt_version_id, PromptVersionBlock.position)
        )
        refs: dict[uuid.UUID, list[tuple[str, int]]] = defaultdict(list)
        for prompt_version_id, block_name, version_number in self._session.execute(stmt):
            refs[prompt_version_id].append((block_name, version_number))
        return dict(refs)

    def block_refs_for_block_versions(
        self, block_version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, int]]]:
        """Pinned (child block name, version number) refs per *parent* block version, in order.

        The block→block twin of :meth:`block_refs_for_prompt_versions`: a block version can
        itself compose other blocks, so its read DTO needs the same composition list a prompt
        version gets. One query for the whole set (no N+1 across a block's history); parent
        versions with no composition simply don't appear in the map.
        """
        if not block_version_ids:
            return {}
        child = aliased(BlockVersion)
        stmt = (
            select(
                BlockVersionBlock.parent_block_version_id,
                Block.name,
                child.version_number,
            )
            .join(child, BlockVersionBlock.child_block_version_id == child.id)
            .join(Block, child.block_id == Block.id)
            .where(BlockVersionBlock.parent_block_version_id.in_(block_version_ids))
            .order_by(BlockVersionBlock.parent_block_version_id, BlockVersionBlock.position)
        )
        refs: dict[uuid.UUID, list[tuple[str, int]]] = defaultdict(list)
        for parent_block_version_id, block_name, version_number in self._session.execute(stmt):
            refs[parent_block_version_id].append((block_name, version_number))
        return dict(refs)

    # ----------------------------------------------------------- render-path
    def get_prompt_top_block_ids(self, prompt_version_id: uuid.UUID) -> list[uuid.UUID]:
        """The direct block versions a prompt version composes, in position order."""
        stmt = (
            select(PromptVersionBlock.block_version_id)
            .where(PromptVersionBlock.prompt_version_id == prompt_version_id)
            .order_by(PromptVersionBlock.position)
        )
        return list(self._session.scalars(stmt))

    def load_block_subgraph(self, roots: list[uuid.UUID]) -> BlockSubgraph:
        """Load every block version transitively reachable from *roots*, with its edges.

        Breadth-first over the block→block table: one query per depth level (a level
        fetches all children of the current frontier), then one query to load the block
        version rows + their block names. Cheap given real composition depth is small.
        """
        roots = list(dict.fromkeys(roots))  # dedupe, preserve order
        if not roots:
            return BlockSubgraph(nodes={})

        all_ids: set[uuid.UUID] = set(roots)
        # parent block version -> [(position, child block version)]
        edges: dict[uuid.UUID, list[tuple[int, uuid.UUID]]] = defaultdict(list)
        frontier: set[uuid.UUID] = set(roots)
        while frontier:
            stmt = select(BlockVersionBlock).where(
                BlockVersionBlock.parent_block_version_id.in_(frontier)
            )
            next_frontier: set[uuid.UUID] = set()
            for edge in self._session.scalars(stmt):
                edges[edge.parent_block_version_id].append(
                    (edge.position, edge.child_block_version_id)
                )
                if edge.child_block_version_id not in all_ids:
                    all_ids.add(edge.child_block_version_id)
                    next_frontier.add(edge.child_block_version_id)
            frontier = next_frontier

        rows = self._session.execute(
            select(BlockVersion, Block.name)
            .join(Block, BlockVersion.block_id == Block.id)
            .where(BlockVersion.id.in_(all_ids))
        ).all()

        nodes: dict[uuid.UUID, BlockNode] = {}
        for version, block_name in rows:
            children = tuple(child for _, child in sorted(edges.get(version.id, [])))
            nodes[version.id] = BlockNode(
                block_version_id=version.id,
                block_id=version.block_id,
                block_name=block_name,
                content=version.content,
                input_variables=tuple(version.input_variables),
                children=children,
            )
        return BlockSubgraph(nodes=nodes)

    # --------------------------------------------------------- cycle guard
    def load_identity_adjacency(self) -> dict[uuid.UUID, set[uuid.UUID]]:
        """Block-identity 'includes' graph: block id -> the block ids it includes.

        Aggregated across **all** block versions (ADR 0015): if any version of block A
        includes any version of block B, the edge A→B is present. Conservative on
        purpose — it keeps the conceptual block-dependency graph a clean DAG.
        """
        parent = aliased(BlockVersion)
        child = aliased(BlockVersion)
        stmt = (
            select(parent.block_id, child.block_id)
            .select_from(BlockVersionBlock)
            .join(parent, BlockVersionBlock.parent_block_version_id == parent.id)
            .join(child, BlockVersionBlock.child_block_version_id == child.id)
        )
        adjacency: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for parent_block_id, child_block_id in self._session.execute(stmt):
            adjacency[parent_block_id].add(child_block_id)
        return adjacency

    def all_block_names(self) -> dict[uuid.UUID, str]:
        """Map every block id to its name — to render a cycle path with readable names."""
        return dict(self._session.execute(select(Block.id, Block.name)).tuples().all())

    # ------------------------------------------------------ impact analysis
    def block_version_ids_for_block(self, block_id: uuid.UUID) -> list[uuid.UUID]:
        """Every version id of one block — the seeds for an impact reverse-walk."""
        stmt = select(BlockVersion.id).where(BlockVersion.block_id == block_id)
        return list(self._session.scalars(stmt))

    def reverse_reachable_block_versions(self, seeds: list[uuid.UUID]) -> set[uuid.UUID]:
        """All block versions that transitively include any of *seeds* (incl. the seeds).

        Reverse BFS over the block→block edges (child -> its parents). Terminates because
        the version graph is acyclic (ADR 0015).
        """
        collected: set[uuid.UUID] = set(seeds)
        frontier: set[uuid.UUID] = set(seeds)
        while frontier:
            stmt = select(BlockVersionBlock.parent_block_version_id).where(
                BlockVersionBlock.child_block_version_id.in_(frontier)
            )
            parents = set(self._session.scalars(stmt))
            frontier = parents - collected
            collected |= frontier
        return collected

    def prompt_versions_referencing(
        self, block_version_ids: set[uuid.UUID]
    ) -> list[tuple[str, int]]:
        """Distinct (prompt name, version number) directly referencing any given block version."""
        if not block_version_ids:
            return []
        stmt = (
            select(Prompt.name, PromptVersion.version_number)
            .select_from(PromptVersionBlock)
            .join(PromptVersion, PromptVersionBlock.prompt_version_id == PromptVersion.id)
            .join(Prompt, PromptVersion.prompt_id == Prompt.id)
            .where(PromptVersionBlock.block_version_id.in_(block_version_ids))
            .distinct()
            .order_by(Prompt.name, PromptVersion.version_number)
        )
        return [(name, number) for name, number in self._session.execute(stmt)]

    def block_versions_info(self, block_version_ids: set[uuid.UUID]) -> list[tuple[str, int]]:
        """(block name, version number) for the given block versions, name-ordered."""
        if not block_version_ids:
            return []
        stmt = (
            select(Block.name, BlockVersion.version_number)
            .join(Block, BlockVersion.block_id == Block.id)
            .where(BlockVersion.id.in_(block_version_ids))
            .order_by(Block.name, BlockVersion.version_number)
        )
        return [(name, number) for name, number in self._session.execute(stmt)]
