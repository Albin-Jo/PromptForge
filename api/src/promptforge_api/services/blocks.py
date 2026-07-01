"""Block business logic: create, version, read, and compose reusable prompt fragments.

A sibling of :class:`promptforge_api.services.prompts.PromptService` — blocks share the
registry's rules (immutable, linearly-versioned content; the ADR-0004 variable
contract) but carry none of the prompt-only concerns (labels, rendering, output
schemas, model settings). Blocks *can* themselves compose other blocks, which is the
only place a dependency cycle can form, so this service runs the cycle guard when a
block version takes references (ADR 0015). It also answers **impact analysis** — the
reverse-graph question "which prompts/blocks depend on this block?".

Speaks plain arguments and ORM entities, never Pydantic (ADR 0003 / CLAUDE.md).
"""

import uuid
from dataclasses import dataclass

from promptforge_api.composition.builder import (
    BlockRef,
    PinnedComposition,
    assert_acyclic,
    pin_composition,
)
from promptforge_api.db.block_models import Block, BlockVersion
from promptforge_api.repositories.blocks import BlockRepository
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.templating import check_variable_contract


class BlockAlreadyExistsError(Exception):
    """Raised when creating a block whose name is already taken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"block '{name}' already exists")
        self.name = name


class BlockNotFoundError(Exception):
    """Raised when a named block does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"block '{name}' not found")
        self.name = name


class BlockVersionNotFoundError(Exception):
    """Raised when a block has no version with the requested number."""

    def __init__(self, name: str, version_number: int) -> None:
        super().__init__(f"block '{name}' has no version {version_number}")
        self.name = name
        self.version_number = version_number


@dataclass(frozen=True)
class ImpactedRef:
    """One artifact (prompt or block) version affected by a block, named for display."""

    name: str
    version_number: int


@dataclass(frozen=True)
class BlockImpact:
    """The blast radius of a block: the prompt and block versions that depend on it."""

    prompts: list[ImpactedRef]
    blocks: list[ImpactedRef]


class BlockInUseError(Exception):
    """Raised when deleting a block that a prompt or another block still composes with.

    We refuse the delete rather than cascade it (ADR 0027): a block is shared infrastructure, so
    deleting it out from under the prompts/blocks that pinned it would silently rewrite their
    meaning. The *transitive* dependents are carried — by name and version — so the UI can name
    exactly which references to detach first. Defined here, beside :class:`BlockImpact`, because it
    carries one.
    """

    def __init__(self, name: str, impact: BlockImpact) -> None:
        parts: list[str] = []
        if impact.prompts:
            parts.append(
                "prompts: " + ", ".join(f"{r.name} v{r.version_number}" for r in impact.prompts)
            )
        if impact.blocks:
            parts.append(
                "blocks: " + ", ".join(f"{r.name} v{r.version_number}" for r in impact.blocks)
            )
        super().__init__(
            f"block '{name}' is in use by {'; '.join(parts)}; detach those references first"
        )
        self.name = name
        self.impact = impact


class BlockService:
    """Use-cases for blocks: create, append versions, read history, compose, impact."""

    def __init__(
        self,
        repository: BlockRepository,
        composition: CompositionRepository | None = None,
    ) -> None:
        self._repository = repository
        # Optional, as in PromptService: a service built without it serves plain blocks
        # and rejects any request carrying block references (a misconfiguration).
        self._composition = composition

    # ----------------------------------------------------------------- create
    def create_block(
        self,
        *,
        name: str,
        role: str,
        description: str | None,
        content: str,
        input_variables: list[str],
        blocks: list[BlockRef] | None = None,
    ) -> Block:
        """Create a block and its immutable version 1 in one transaction.

        A brand-new block cannot be part of a cycle — nothing references it yet — so the
        cycle guard is skipped here; it only matters when *adding a version* to an
        existing block (which other blocks may already point at).
        """
        if self._repository.get_by_name(name) is not None:
            raise BlockAlreadyExistsError(name)

        pinned = self._pin(blocks)
        self._validate(content, input_variables, pinned)

        block = Block(name=name, role=role, description=description)
        version = BlockVersion(version_number=1, content=content, input_variables=input_variables)
        block.versions.append(version)
        self._repository.add(block)
        self._repository.flush()
        self._persist_block_blocks(version.id, pinned)
        return self._require_block(name)

    def add_version(
        self,
        *,
        name: str,
        content: str,
        input_variables: list[str],
        blocks: list[BlockRef] | None = None,
    ) -> BlockVersion:
        """Append the next immutable version to an existing block (linear lineage)."""
        block = self._require_block(name)
        pinned = self._pin(blocks)
        if pinned is not None:
            assert self._composition is not None  # guaranteed when pinned is not None
            # Refuse before writing anything if these references would close a cycle.
            assert_acyclic(self._composition, block.id, block.name, pinned.direct_block_ids)
        self._validate(content, input_variables, pinned)

        # versions are loaded ordered by version_number, so the last is the latest.
        latest = block.versions[-1]
        version = BlockVersion(
            version_number=latest.version_number + 1,
            parent_version_id=latest.id,
            content=content,
            input_variables=input_variables,
        )
        # Append through the relationship so the in-memory aggregate stays consistent
        # and the cascade inserts the row; flush populates server defaults (created_at).
        block.versions.append(version)
        self._repository.flush()
        self._persist_block_blocks(version.id, pinned)
        return version

    # ------------------------------------------------------------------- read
    def get_block(self, name: str) -> Block | None:
        """Return a block with its versions, or ``None`` if it doesn't exist."""
        return self._repository.get_by_name(name)

    def list_blocks(self) -> list[Block]:
        """Return every block with its version history, newest block first."""
        return self._repository.list_all()

    def list_versions(self, name: str) -> list[BlockVersion]:
        """Return a block's version history, oldest first."""
        return list(self._require_block(name).versions)

    def version_block_refs(
        self, version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, int]]]:
        """Pinned (child block name, version) refs per block-version id, so reads show composition.

        Empty when no composition repo is wired (a service serving plain blocks). Mirrors
        :meth:`PromptService.version_block_refs` — the read endpoints attach these so the editor
        can carry a block's composition forward when adding a new version.
        """
        if self._composition is None:
            return {}
        return self._composition.block_refs_for_block_versions(version_ids)

    def get_version(self, name: str, version_number: int) -> BlockVersion:
        """Fetch one version of a block by its number."""
        version = self._find_version(self._require_block(name), version_number)
        if version is None:
            raise BlockVersionNotFoundError(name, version_number)
        return version

    # --------------------------------------------------------- impact analysis
    def impact_of(self, name: str) -> BlockImpact:
        """Which prompts and blocks depend on this block — the reverse graph (ADR 0015).

        Walks the composition graph *backwards* from every version of this block: the
        prompt versions that (transitively, via pinned edges) include it, and the other
        block versions that include it. This is the "edit a shared block → see who's
        affected" answer; the walk is exact (it follows pinned edges) and terminates
        because the version graph is acyclic.
        """
        return self._impact_of(self._require_block(name))

    def _impact_of(self, block: Block) -> BlockImpact:
        """Impact analysis for an already-loaded block (shared by :meth:`impact_of`/delete)."""
        if self._composition is None:
            return BlockImpact(prompts=[], blocks=[])

        seeds = self._composition.block_version_ids_for_block(block.id)
        if not seeds:
            return BlockImpact(prompts=[], blocks=[])

        reachable = self._composition.reverse_reachable_block_versions(seeds)
        prompt_rows = self._composition.prompt_versions_referencing(reachable)
        # The other block versions that include this one (exclude the block's own versions).
        block_rows = self._composition.block_versions_info(reachable - set(seeds))
        return BlockImpact(
            prompts=[ImpactedRef(name=n, version_number=v) for n, v in prompt_rows],
            blocks=[ImpactedRef(name=n, version_number=v) for n, v in block_rows],
        )

    # ----------------------------------------------------------------- delete
    def delete_block(self, name: str) -> None:
        """Delete a block — unless a prompt or another block still composes with it (ADR 0027).

        Mirrors :meth:`EvalService.delete_dataset`. Fail-closed: if anything (transitively) depends
        on this block we refuse with the named dependents rather than cascade the delete and
        silently rewrite the prompts/blocks that pinned it. A leaf block's versions and its own
        *outgoing* composition edges go via the existing ORM/FK cascades, so no orphan rows remain.
        """
        block = self._require_block(name)
        impact = self._impact_of(block)
        if impact.prompts or impact.blocks:
            raise BlockInUseError(name, impact)
        self._repository.delete(block)
        self._repository.flush()

    # ----------------------------------------------------------------- shared
    def _pin(self, blocks: list[BlockRef] | None) -> PinnedComposition | None:
        """Resolve block references to a pinned composition, or ``None`` if uncomposed."""
        if not blocks:
            return None
        if self._composition is None:
            raise RuntimeError("composition repository not configured")
        return pin_composition(self._composition, blocks)

    def _validate(
        self, content: str, input_variables: list[str], pinned: PinnedComposition | None
    ) -> None:
        """Enforce the variable contract, widened by any inherited block variables."""
        inherited = pinned.inherited_variables if pinned is not None else ()
        check_variable_contract(content, input_variables, extra_required=inherited)

    def _persist_block_blocks(
        self, parent_block_version_id: uuid.UUID, pinned: PinnedComposition | None
    ) -> None:
        """Write the block→block edges in position order (no-op when uncomposed)."""
        if pinned is None:
            return
        assert self._composition is not None  # guaranteed when pinned is not None
        for position, child_block_version_id in enumerate(pinned.block_version_ids):
            self._composition.add_block_block(
                parent_block_version_id, child_block_version_id, position
            )
        self._repository.flush()

    def _require_block(self, name: str) -> Block:
        block = self._repository.get_by_name(name)
        if block is None:
            raise BlockNotFoundError(name)
        return block

    @staticmethod
    def _find_version(block: Block, version_number: int) -> BlockVersion | None:
        return next((v for v in block.versions if v.version_number == version_number), None)
