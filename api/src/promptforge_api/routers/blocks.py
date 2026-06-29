"""HTTP layer for blocks — the reusable fragments prompts compose from.

Translates requests/responses only; no business logic, no SQL. Domain errors raised
by :class:`BlockService` are turned into status codes by the handlers registered in
:mod:`promptforge_api.errors`. Handlers are ``def`` (not ``async def``) so FastAPI
runs them in a threadpool and the synchronous DB session never blocks the event loop
(ADR 0003) — the same shape as the prompts router.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from promptforge_api.authz import require_editor
from promptforge_api.composition.builder import BlockRef
from promptforge_api.db.engine import get_session
from promptforge_api.repositories.blocks import BlockRepository
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.schemas import (
    BlockCreate,
    BlockImpactResponse,
    BlockRead,
    BlockRefDTO,
    BlockVersionCreate,
    BlockVersionRead,
    ImpactedRefDTO,
)
from promptforge_api.services.blocks import (
    BlockImpact,
    BlockNotFoundError,
    BlockService,
    ImpactedRef,
)

router = APIRouter(prefix="/blocks", tags=["blocks"])

SessionDep = Annotated[Session, Depends(get_session)]


def _to_block_refs(refs: list[BlockRefDTO]) -> list[BlockRef]:
    """Map composition reference DTOs onto the service's domain ``BlockRef``s."""
    return [BlockRef(block=ref.block, version=ref.version) for ref in refs]


def _with_blocks(versions: list[BlockVersionRead], service: BlockService) -> None:
    """Populate each version's composition refs in place (ADR 0015 read-model).

    Block→block edges live in the composition tables, not on the BlockVersion row, so the read
    DTOs come back with an empty list until we attach them here. One query for all versions —
    the same read-model shape as the prompts router's ``_with_blocks``.
    """
    refs = service.version_block_refs([v.id for v in versions])
    for version in versions:
        version.blocks = [
            BlockRefDTO(block=name, version=number) for name, number in refs.get(version.id, [])
        ]


def get_block_service(session: SessionDep) -> BlockService:
    """Assemble the service with a request-scoped session + composition access."""
    return BlockService(BlockRepository(session), CompositionRepository(session))


ServiceDep = Annotated[BlockService, Depends(get_block_service)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockRead,
    dependencies=[Depends(require_editor)],
)
def create_block(payload: BlockCreate, service: ServiceDep) -> BlockRead:
    """Create a block and its first version (optionally composing other blocks)."""
    block = service.create_block(
        name=payload.name,
        role=payload.role,
        description=payload.description,
        content=payload.content,
        input_variables=payload.input_variables,
        blocks=_to_block_refs(payload.blocks),
    )
    read = BlockRead.model_validate(block)
    _with_blocks(read.versions, service)
    return read


@router.get("", response_model=list[BlockRead])
def list_blocks(service: ServiceDep) -> list[BlockRead]:
    """List every block with its version history, newest block first."""
    reads = [BlockRead.model_validate(b) for b in service.list_blocks()]
    _with_blocks([v for r in reads for v in r.versions], service)
    return reads


@router.get("/{name}", response_model=BlockRead)
def get_block(name: str, service: ServiceDep) -> BlockRead:
    """Fetch a block with its version history by name."""
    block = service.get_block(name)
    if block is None:
        raise BlockNotFoundError(name)
    read = BlockRead.model_validate(block)
    _with_blocks(read.versions, service)
    return read


@router.post(
    "/{name}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockVersionRead,
    dependencies=[Depends(require_editor)],
)
def create_version(name: str, payload: BlockVersionCreate, service: ServiceDep) -> BlockVersionRead:
    """Append a new immutable version to an existing block (optionally composing blocks)."""
    version = service.add_version(
        name=name,
        content=payload.content,
        input_variables=payload.input_variables,
        blocks=_to_block_refs(payload.blocks),
    )
    read = BlockVersionRead.model_validate(version)
    _with_blocks([read], service)
    return read


@router.get("/{name}/versions", response_model=list[BlockVersionRead])
def list_versions(name: str, service: ServiceDep) -> list[BlockVersionRead]:
    """List a block's version history, oldest first."""
    reads = [BlockVersionRead.model_validate(v) for v in service.list_versions(name)]
    _with_blocks(reads, service)
    return reads


@router.get("/{name}/versions/{version_number}", response_model=BlockVersionRead)
def get_version(name: str, version_number: int, service: ServiceDep) -> BlockVersionRead:
    """Fetch a single version of a block by number."""
    read = BlockVersionRead.model_validate(service.get_version(name, version_number))
    _with_blocks([read], service)
    return read


@router.get("/{name}/impact", response_model=BlockImpactResponse)
def block_impact(name: str, service: ServiceDep) -> BlockImpactResponse:
    """Impact analysis: which prompts/blocks depend on this block (the reverse graph)."""
    return _to_impact_response(name, service.impact_of(name))


def _to_impact_response(name: str, impact: BlockImpact) -> BlockImpactResponse:
    """Map the service's domain ``BlockImpact`` onto the API DTO."""

    def _refs(refs: list[ImpactedRef]) -> list[ImpactedRefDTO]:
        return [ImpactedRefDTO(name=r.name, version_number=r.version_number) for r in refs]

    return BlockImpactResponse(
        block=name, prompts=_refs(impact.prompts), blocks=_refs(impact.blocks)
    )
