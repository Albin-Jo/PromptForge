"""HTTP layer for golden sets (datasets). Translation only — no business logic, no SQL.

A golden set is the curated input→reference cases a prompt is graded against; attaching one to
a prompt is what makes the prompt promotable (Sprint 11). Creating/reading datasets lives here;
attaching one, triggering an eval, and reading a version's eval status live on the prompts router
(they're keyed by prompt). Handlers are ``def`` (threadpool) so the sync DB session never blocks
the event loop (ADR 0003).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from promptforge_api import enqueue
from promptforge_api.authz import require_editor
from promptforge_api.db.engine import get_session
from promptforge_api.db.eval_models import Dataset
from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.schemas import (
    DatasetCreate,
    DatasetDetail,
    DatasetItemDTO,
    DatasetRead,
    DatasetUpdate,
)
from promptforge_api.services.evals import DatasetItemInput, EvalService

router = APIRouter(prefix="/datasets", tags=["datasets"])

SessionDep = Annotated[Session, Depends(get_session)]


def get_eval_service(session: SessionDep) -> EvalService:
    """Assemble the eval service with a request-scoped session."""
    return EvalService(
        EvalRepository(session), PromptRepository(session), submit_eval=enqueue.submit_eval
    )


EvalServiceDep = Annotated[EvalService, Depends(get_eval_service)]


def _to_dataset_read(dataset: Dataset, item_count: int | None = None) -> DatasetRead:
    """Map a dataset entity onto the API DTO (item count, not the full case list).

    ``item_count`` is passed explicitly by the list handler (it counts DB-side and never loads
    the items); create/get/update have the items loaded, so they fall back to ``len``.
    """
    return DatasetRead(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        created_at=dataset.created_at,
        item_count=item_count if item_count is not None else len(dataset.items),
    )


def _to_item_inputs(items: list[DatasetItemDTO]) -> list[DatasetItemInput]:
    """Map the case DTOs onto the service's domain inputs (shared by create + update)."""
    return [
        DatasetItemInput(input=i.input, reference=i.reference, metadata=i.metadata) for i in items
    ]


def _to_dataset_detail(dataset: Dataset) -> DatasetDetail:
    """Map a dataset entity onto the detail DTO — the count read plus its case bodies."""
    return DatasetDetail(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        created_at=dataset.created_at,
        item_count=len(dataset.items),
        items=[
            DatasetItemDTO(input=i.input, reference=i.reference, metadata=i.item_metadata)
            for i in dataset.items
        ],
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DatasetRead,
    dependencies=[Depends(require_editor)],
)
def create_dataset(payload: DatasetCreate, service: EvalServiceDep) -> DatasetRead:
    """Create a golden set with its cases."""
    dataset = service.create_dataset(
        name=payload.name,
        description=payload.description,
        items=_to_item_inputs(payload.items),
    )
    return _to_dataset_read(dataset)


@router.get("", response_model=list[DatasetRead])
def list_datasets(service: EvalServiceDep) -> list[DatasetRead]:
    """List every golden set with its case count (no case bodies), name-ordered."""
    return [_to_dataset_read(dataset, count) for dataset, count in service.list_datasets()]


@router.get("/{name}", response_model=DatasetDetail)
def get_dataset(name: str, service: EvalServiceDep) -> DatasetDetail:
    """Fetch a golden set by name, *with* its cases (what the editor prefills from)."""
    return _to_dataset_detail(service.get_dataset(name))


@router.put(
    "/{name}",
    response_model=DatasetRead,
    dependencies=[Depends(require_editor)],
)
def update_dataset(name: str, payload: DatasetUpdate, service: EvalServiceDep) -> DatasetRead:
    """Replace a golden set's description and cases wholesale (ADR 0024 — not a per-case patch)."""
    dataset = service.update_dataset(
        name=name,
        description=payload.description,
        items=_to_item_inputs(payload.items),
    )
    return _to_dataset_read(dataset)


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_dataset(name: str, service: EvalServiceDep) -> None:
    """Delete a golden set; refuses with 409 if a prompt still gates on it (ADR 0024)."""
    service.delete_dataset(name)
