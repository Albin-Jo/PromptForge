"""HTTP layer for prompts. Translates requests/responses; no business logic, no
SQL. Domain errors raised by the service are turned into status codes by the
handlers registered in :mod:`promptforge_api.errors`.

Handlers are ``def`` (not ``async def``) on purpose: FastAPI runs them in a
threadpool so the synchronous DB session never blocks the event loop (ADR 0003).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from promptforge_api import enqueue
from promptforge_api.authz import audit_actor, require_admin, require_editor
from promptforge_api.cache import get_cache, get_cache_stats
from promptforge_api.composition.builder import BlockRef
from promptforge_api.config import Settings, get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.db.user_models import User
from promptforge_api.promotion import PromotionPolicy
from promptforge_api.repositories.audit import AuditRepository
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.repositories.scans import ScanRepository
from promptforge_api.schemas import (
    BlockRefDTO,
    CacheStatsResponse,
    EvalRunAccepted,
    EvalRunSummary,
    EvalStatusResponse,
    GoldenSetAttach,
    LabelRead,
    LabelSet,
    PromptCreate,
    PromptRead,
    PromptSummaryRead,
    PromptVersionRead,
    RenderByLabelRequest,
    RenderRequest,
    RenderResponse,
    ScanAccepted,
    ScanRunSummary,
    ScanStatusResponse,
    VersionCreate,
)
from promptforge_api.security import require_api_key
from promptforge_api.security_gate import SecurityGatePolicy
from promptforge_api.services.evals import EvalService
from promptforge_api.services.promotion import (
    PromotionBlocked,
    PromotionGate,
    PromotionPending,
    PromotionPromoted,
)
from promptforge_api.services.prompts import (
    PromptNotFoundError,
    PromptService,
    RenderedPrompt,
)
from promptforge_api.services.scans import ScanService

router = APIRouter(prefix="/prompts", tags=["prompts"])

SessionDep = Annotated[Session, Depends(get_session)]


def _to_block_refs(refs: list[BlockRefDTO]) -> list[BlockRef]:
    """Map composition reference DTOs onto the service's domain ``BlockRef``s."""
    return [BlockRef(block=ref.block, version=ref.version) for ref in refs]


def _to_render_response(rendered: RenderedPrompt) -> RenderResponse:
    """Map the service's domain ``RenderedPrompt`` onto the API DTO (keeps Pydantic out
    of the service layer, ADR 0003)."""
    return RenderResponse(
        prompt=rendered.prompt,
        model_settings=rendered.model_settings,
        output_schema=rendered.output_schema,
        prompt_id=rendered.prompt_id,
        prompt_version_id=rendered.prompt_version_id,
        version_number=rendered.version_number,
    )


def _eval_service(session: Session) -> EvalService:
    """The eval/golden-set service, wired to the real Celery enqueue + the audit sink."""
    return EvalService(
        EvalRepository(session),
        PromptRepository(session),
        submit_eval=enqueue.submit_eval,
        audits=AuditRepository(session),
    )


def get_eval_service(session: SessionDep) -> EvalService:
    """Request-scoped eval service for the prompt-keyed eval endpoints."""
    return _eval_service(session)


def _scan_service(session: Session) -> ScanService:
    """The scanning service, wired to the real Celery enqueue."""
    return ScanService(
        ScanRepository(session), PromptRepository(session), submit_scan=enqueue.submit_scan
    )


def get_scan_service(session: SessionDep) -> ScanService:
    """Request-scoped scan service for the prompt-keyed scan endpoints."""
    return _scan_service(session)


def get_prompt_service(session: SessionDep) -> PromptService:
    """Assemble the service with a request-scoped session, cache, the promotion gate, and scans."""
    settings = get_settings()
    audits = AuditRepository(session)
    gate = PromotionGate(
        _eval_service(session),
        audits,
        policy=PromotionPolicy.from_settings(settings),
        submit_webhook=enqueue.make_webhook_submit(settings),
        scans=_scan_service(session),
        security_policy=SecurityGatePolicy.from_settings(settings),
    )
    return PromptService(
        PromptRepository(session),
        get_cache(),
        composition=CompositionRepository(session),
        gate=gate,
        scans=_scan_service(session),
        audits=audits,
        cache_ttl_seconds=settings.render_cache_ttl_seconds,
        cache_stats=get_cache_stats(),
    )


ServiceDep = Annotated[PromptService, Depends(get_prompt_service)]
EvalServiceDep = Annotated[EvalService, Depends(get_eval_service)]
ScanServiceDep = Annotated[ScanService, Depends(get_scan_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("", response_model=list[PromptSummaryRead])
def list_prompts(service: ServiceDep) -> list[PromptSummaryRead]:
    """List all prompts as lightweight summaries (name-ordered). Powers the UI list view."""
    return [PromptSummaryRead.model_validate(s) for s in service.list_prompts()]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PromptRead,
)
def create_prompt(
    payload: PromptCreate,
    service: ServiceDep,
    actor_user: Annotated[User | None, Depends(require_editor)],
) -> PromptRead:
    """Create a prompt and its first version. Authoring action — editor or admin."""
    prompt = service.create_prompt(
        name=payload.name,
        description=payload.description,
        content=payload.content,
        input_variables=payload.input_variables,
        model_settings=payload.model_settings,
        output_schema=payload.output_schema,
        blocks=_to_block_refs(payload.blocks),
        actor=audit_actor(actor_user),
    )
    return PromptRead.model_validate(prompt)


def _with_blocks(versions: list[PromptVersionRead], service: ServiceDep) -> None:
    """Populate each version's composition refs in place (ADR 0015 read-model).

    Blocks live in the composition tables, not on the PromptVersion row, so the read DTOs
    come back with an empty list until we attach them here. One query for all versions.
    """
    refs = service.version_block_refs([v.id for v in versions])
    for version in versions:
        version.blocks = [
            BlockRefDTO(block=name, version=number) for name, number in refs.get(version.id, [])
        ]


@router.get("/{name}", response_model=PromptRead)
def get_prompt(name: str, service: ServiceDep) -> PromptRead:
    """Fetch a prompt with its version history by name."""
    prompt = service.get_prompt(name)
    if prompt is None:
        raise PromptNotFoundError(name)
    read = PromptRead.model_validate(prompt)
    _with_blocks(read.versions, service)
    return read


@router.post(
    "/{name}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=PromptVersionRead,
)
def create_version(
    name: str,
    payload: VersionCreate,
    service: ServiceDep,
    actor_user: Annotated[User | None, Depends(require_editor)],
) -> PromptVersionRead:
    """Append a new immutable version to an existing prompt. Authoring action — editor or admin."""
    version = service.add_version(
        name=name,
        content=payload.content,
        input_variables=payload.input_variables,
        model_settings=payload.model_settings,
        output_schema=payload.output_schema,
        blocks=_to_block_refs(payload.blocks),
        actor=audit_actor(actor_user),
    )
    return PromptVersionRead.model_validate(version)


@router.get("/{name}/versions", response_model=list[PromptVersionRead])
def list_versions(name: str, service: ServiceDep) -> list[PromptVersionRead]:
    """List a prompt's version history, oldest first.

    API-only (Sprint 30 T4): provided for the SDK / CLI / curl. The browser reads history from the
    aggregate ``GET /prompts/{name}``, so the UI never calls this route. Adopting these routes to
    fix that aggregate's over-fetch is tracked separately (docs/learning-backlog.md, Sprint 3 tech
    debt) and is deliberately *not* built here.
    """
    versions = service.list_versions(name)
    reads = [PromptVersionRead.model_validate(v) for v in versions]
    _with_blocks(reads, service)
    return reads


@router.get("/{name}/versions/{version_number}", response_model=PromptVersionRead)
def get_version(name: str, version_number: int, service: ServiceDep) -> PromptVersionRead:
    """Fetch a single version of a prompt by number.

    API-only (Sprint 30 T4): provided for the SDK / CLI / curl. The browser reads a specific version
    from the aggregate ``GET /prompts/{name}`` it already holds, so the UI never calls this route.
    The matching over-fetch in ``get_version`` is tracked separately (docs/learning-backlog.md,
    Sprint 3 tech debt) and is deliberately *not* fixed here.
    """
    version = service.get_version(name, version_number)
    read = PromptVersionRead.model_validate(version)
    _with_blocks([read], service)
    return read


@router.post(
    "/{name}/versions/{version_number}/render",
    response_model=RenderResponse,
)
def render_version(
    name: str,
    version_number: int,
    payload: RenderRequest,
    service: ServiceDep,
) -> RenderResponse:
    """Render a version with variables into a finished prompt + model config."""
    rendered = service.render(name=name, version_number=version_number, variables=payload.variables)
    return _to_render_response(rendered)


@router.post(
    "/{name}/render",
    response_model=RenderResponse,
    dependencies=[Depends(require_api_key)],
)
def render_by_label(
    name: str, payload: RenderByLabelRequest, service: ServiceDep
) -> RenderResponse:
    """Render the version a label points at — the SDK's one-call fetch (floating).

    Protected by :func:`require_api_key`: SDK clients must send a valid ``X-API-Key``
    when keys are configured (open otherwise).
    """
    rendered = service.render_by_label(name=name, label=payload.label, variables=payload.variables)
    return _to_render_response(rendered)


@router.get(
    "/{name}/cache",
    response_model=CacheStatsResponse,
    dependencies=[Depends(require_admin)],
)
def get_render_cache_stats(
    name: str, service: ServiceDep, settings: SettingsDep
) -> CacheStatsResponse:
    """Render-cache hit-rate for a prompt (admin-only).

    Cumulative since the process started and per-process (ADR-free, see CacheStats); ``ttl_seconds``
    is the cache TTL for context. 404 if the prompt doesn't exist.
    """
    stats = service.render_cache_stats(name)
    return CacheStatsResponse(
        prompt=name,
        hits=stats.hits,
        misses=stats.misses,
        total=stats.total,
        hit_rate=stats.hit_rate,
        ttl_seconds=settings.render_cache_ttl_seconds,
    )


@router.put(
    "/{name}/labels/{label}",
    response_model=LabelRead,
    responses={
        409: {
            "description": (
                "The promotion was refused: the candidate regressed / is below the quality bar "
                "(`promotion` carries the per-metric scores), or its eval is still running "
                "(`eval_run_id` to poll). Only the gated label is quality-checked."
            )
        }
    },
)
def set_label(
    name: str,
    label: str,
    payload: LabelSet,
    service: ServiceDep,
    actor_user: Annotated[User | None, Depends(require_admin)],
) -> Response:
    """Point a label at a version (creating or moving it). Moving the gated label = a deploy.

    Moving the **gated label** runs the eval gate (Sprint 11): a candidate that regressed or is
    below the floor is refused with **409** and the failing scores; one whose eval hasn't finished
    gets **409** with the ``eval_run_id`` to poll. Any other label moves freely.
    """
    result = service.set_label(
        name=name, label=label, version_number=payload.version_number, actor=audit_actor(actor_user)
    )
    if isinstance(result, PromotionPromoted):
        body = LabelRead(
            name=result.label.name,
            version=PromptVersionRead.model_validate(result.label.version),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(body))
    if isinstance(result, PromotionPending):
        # The pending job is an eval or a scan; surface its id under a kind-specific key.
        id_key = "eval_run_id" if result.kind == "eval" else "security_scan_id"
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": result.message, id_key: str(result.run_id)},
        )
    # PromotionBlocked
    assert isinstance(result, PromotionBlocked)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=jsonable_encoder({"detail": result.reason, "promotion": result.detail}),
    )


@router.get("/{name}/labels/{label}", response_model=PromptVersionRead)
def resolve_label(name: str, label: str, service: ServiceDep) -> PromptVersionRead:
    """Resolve a label to the version it currently points at."""
    version = service.resolve_label(name, label)
    return PromptVersionRead.model_validate(version)


@router.put(
    "/{name}/golden-set",
    response_model=PromptRead,
)
def attach_golden_set(
    name: str,
    payload: GoldenSetAttach,
    service: EvalServiceDep,
    actor_user: Annotated[User | None, Depends(require_editor)],
) -> PromptRead:
    """Point a prompt at the golden set it must clear to be promoted (Sprint 11)."""
    prompt = service.attach_golden_set(
        prompt_name=name, dataset_name=payload.dataset, actor=audit_actor(actor_user)
    )
    return PromptRead.model_validate(prompt)


@router.delete(
    "/{name}/golden-set",
    response_model=PromptRead,
)
def detach_golden_set(
    name: str,
    service: EvalServiceDep,
    actor_user: Annotated[User | None, Depends(require_editor)],
) -> PromptRead:
    """Clear a prompt's golden set (so it has no promotion gate, and its set can be deleted)."""
    prompt = service.detach_golden_set(prompt_name=name, actor=audit_actor(actor_user))
    return PromptRead.model_validate(prompt)


@router.post(
    "/{name}/versions/{version_number}/evaluate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvalRunAccepted,
    dependencies=[Depends(require_editor)],
)
def evaluate_version(name: str, version_number: int, service: EvalServiceDep) -> EvalRunAccepted:
    """Trigger a gating eval of one version against the prompt's golden set (async)."""
    run = service.evaluate_version(prompt_name=name, version_number=version_number)
    return EvalRunAccepted(eval_run_id=run.id, status=run.status)


@router.get(
    "/{name}/versions/{version_number}/eval",
    response_model=EvalStatusResponse,
)
def get_eval_status(name: str, version_number: int, service: EvalServiceDep) -> EvalStatusResponse:
    """Report a version's derived eval state + the latest run's score summary."""
    view = service.version_eval_status(prompt_name=name, version_number=version_number)
    return EvalStatusResponse(
        prompt=name,
        version_number=view.version_number,
        prompt_version_id=view.prompt_version_id,
        status=view.status,
        latest_run_id=view.latest_run_id,
        summary=view.summary,
    )


@router.get(
    "/{name}/versions/{version_number}/evals",
    response_model=list[EvalRunSummary],
)
def list_eval_runs(
    name: str, version_number: int, service: EvalServiceDep
) -> list[EvalRunSummary]:
    """List a version's eval runs, newest first — the audit history behind the latest status."""
    runs = service.list_version_runs(prompt_name=name, version_number=version_number)
    return [
        EvalRunSummary(
            id=run.id,
            status=run.status,
            scorers=[spec["scorer"] for spec in run.scorer_config if "scorer" in spec],
            created_at=run.created_at,
            completed_at=run.completed_at,
            summary=run.summary,
        )
        for run in runs
    ]


@router.post(
    "/{name}/versions/{version_number}/scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScanAccepted,
    dependencies=[Depends(require_editor)],
)
def scan_version(name: str, version_number: int, service: ScanServiceDep) -> ScanAccepted:
    """Trigger a security scan of one version (async). Scans also run automatically on save."""
    scan = service.scan_version(prompt_name=name, version_number=version_number)
    return ScanAccepted(security_scan_id=scan.id, status=scan.status)


@router.get(
    "/{name}/versions/{version_number}/scans",
    response_model=list[ScanRunSummary],
)
def list_scan_runs(
    name: str, version_number: int, service: ScanServiceDep
) -> list[ScanRunSummary]:
    """List a version's security scans, newest first — audit history behind the latest status."""
    scans = service.list_version_scans(prompt_name=name, version_number=version_number)
    return [
        ScanRunSummary(
            id=scan.id,
            status=scan.status,
            scanners=scan.scanners,
            risk_level=scan.risk_level,
            findings=scan.findings,
            created_at=scan.created_at,
            completed_at=scan.completed_at,
        )
        for scan in scans
    ]


@router.get(
    "/{name}/versions/{version_number}/scan",
    response_model=ScanStatusResponse,
)
def get_scan_status(name: str, version_number: int, service: ScanServiceDep) -> ScanStatusResponse:
    """Report a version's derived scan state: risk level + the findings from the latest scan."""
    view = service.version_scan_status(prompt_name=name, version_number=version_number)
    return ScanStatusResponse(
        prompt=name,
        version_number=view.version_number,
        prompt_version_id=view.prompt_version_id,
        status=view.status,
        latest_scan_id=view.latest_scan_id,
        risk_level=view.risk_level,
        findings=view.findings,
    )
