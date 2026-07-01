"""Pydantic DTOs — the API boundary.

These live *only* at the edge: routers validate requests into them and serialize
responses out of them. Services and repositories never import this module, so
Pydantic never leaks into the domain/persistence layers (ADR 0003 / CLAUDE.md).
``from_attributes=True`` lets a response model be built straight from an ORM
instance's attributes.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A prompt name is also a URL path segment (GET /prompts/{name}) and the SDK's
# lookup key, so we constrain it to a safe slug rather than arbitrary text.
_NAME_PATTERN = r"^[a-zA-Z0-9._-]+$"


class BlockRefDTO(BaseModel):
    """A pinned reference to an exact block version (ADR 0015), by name + number."""

    block: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)


class VersionContent(BaseModel):
    """The body of a version: template text plus its declared metadata.

    Shared by prompt-create and add-version so the version contract is defined
    once. ``input_variables`` must match the template's ``{{placeholders}}`` *plus*
    any variables inherited from referenced blocks — the service enforces it (ADR 0004).
    """

    content: str = Field(min_length=1)
    input_variables: list[str] = Field(default_factory=list)
    # Free-form provider/model/params; structured by the gateway later (Phase 3).
    model_settings: dict[str, Any] | None = None
    # An optional JSON Schema for the expected model-output shape.
    output_schema: dict[str, Any] | None = None
    # Ordered, pinned block references this version composes from (empty = plain prompt).
    blocks: list[BlockRefDTO] = Field(default_factory=list)


class PromptCreate(VersionContent):
    """Request body for creating a prompt together with its first version."""

    name: str = Field(min_length=1, max_length=255, pattern=_NAME_PATTERN)
    description: str | None = None


class VersionCreate(VersionContent):
    """Request body for appending a new version to an existing prompt."""


class PromptVersionRead(BaseModel):
    """An immutable version as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    parent_version_id: uuid.UUID | None
    content: str
    input_variables: list[str]
    model_settings: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    created_at: datetime
    # Pinned block references this version composes from, in order (ADR 0015). Empty for a
    # plain prompt. Populated by the read endpoints from the composition tables — not an ORM
    # column on PromptVersion — so the UI can carry composition forward when editing.
    blocks: list[BlockRefDTO] = Field(default_factory=list)


class PromptRead(BaseModel):
    """A prompt with its version history, as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[PromptVersionRead]
    # The golden set this prompt must clear to be promoted, by id (None = no gate attached yet).
    # A bare id, not the name: the model keeps a bare FK (no cross-module relationship), and the UI
    # already has the datasets list to resolve id → name. Auto-populated by from_attributes.
    golden_set_id: uuid.UUID | None = None


class PromptSummaryRead(BaseModel):
    """A lightweight prompt row for the list view — no version bodies."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    latest_version: int | None
    version_count: int
    created_at: datetime
    updated_at: datetime


class LabelSet(BaseModel):
    """Request body for pointing a label at a version."""

    version_number: int = Field(ge=1)


class LabelRead(BaseModel):
    """A label pointer and the version it resolves to."""

    name: str
    version: PromptVersionRead


class RenderRequest(BaseModel):
    """Variables to fill a version's template."""

    variables: dict[str, str] = Field(default_factory=dict)


class RenderByLabelRequest(BaseModel):
    """Render the version a label points at, with these variables (the SDK's call)."""

    label: str = Field(min_length=1)
    variables: dict[str, str] = Field(default_factory=dict)


# --- Blocks (composable prompts) -------------------------------------------------

# The block's role is a closed set; a Literal makes the API reject an invalid role at
# the boundary with a clear 422, before it ever reaches the service or the DB CHECK.
BlockRole = Literal["role", "context", "guardrails", "output_format", "other"]


class BlockVersionContent(BaseModel):
    """The body of a block version: template text plus its declared variables.

    Shared by block-create and add-version so the contract is defined once;
    ``input_variables`` must match the template's ``{{placeholders}}`` plus any variables
    inherited from referenced blocks (ADR 0004). A block may itself compose other blocks.
    """

    content: str = Field(min_length=1)
    input_variables: list[str] = Field(default_factory=list)
    # Ordered, pinned block references this block composes from (empty = leaf block).
    blocks: list[BlockRefDTO] = Field(default_factory=list)


class BlockCreate(BlockVersionContent):
    """Request body for creating a block together with its first version."""

    name: str = Field(min_length=1, max_length=255, pattern=_NAME_PATTERN)
    role: BlockRole
    description: str | None = None


class BlockVersionCreate(BlockVersionContent):
    """Request body for appending a new version to an existing block."""


class BlockVersionRead(BaseModel):
    """An immutable block version as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    parent_version_id: uuid.UUID | None
    content: str
    input_variables: list[str]
    created_at: datetime
    # Pinned block references this version composes from, in order (ADR 0015). Empty for a leaf
    # block. Like PromptVersionRead.blocks, populated by the read endpoints from the composition
    # tables — not an ORM column — so the editor can carry composition forward on a new version.
    blocks: list[BlockRefDTO] = Field(default_factory=list)


class BlockRead(BaseModel):
    """A block with its version history, as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: BlockRole
    description: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[BlockVersionRead]


class ImpactedRefDTO(BaseModel):
    """One affected artifact version (a prompt or a block), named for display."""

    name: str
    version_number: int


class BlockImpactResponse(BaseModel):
    """Impact analysis for a block: who depends on it (the reverse dependency graph).

    ``prompts`` are the prompt versions that (transitively) include the block — the
    "edit this block → these are affected" answer; ``blocks`` are the other block
    versions that include it.
    """

    block: str
    prompts: list[ImpactedRefDTO]
    blocks: list[ImpactedRefDTO]


class LatencyPercentilesDTO(BaseModel):
    """Latency distribution in milliseconds; each value is null when no latency was recorded."""

    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class MetricsBlockDTO(BaseModel):
    """Aggregate over a set of executions: volume, errors, latency, spend.

    ``total_cost_usd`` is a *string* (e.g. ``"0.000450"``), not a float, so money keeps its exact
    decimal value across the wire — a JSON float would reintroduce the rounding the server avoids.
    """

    request_count: int
    error_count: int
    error_rate: float | None
    latency: LatencyPercentilesDTO
    total_cost_usd: str | None


class VersionMetricsDTO(BaseModel):
    """One version's block, plus its latest eval quality (mean scorer value in [0,1], or null)."""

    version_number: int
    prompt_version_id: uuid.UUID
    quality: float | None
    metrics: MetricsBlockDTO


class SourceCostDTO(BaseModel):
    """Spend attributed to one feature/source."""

    source: str | None
    cost_usd: str | None


class PromptMetricsResponse(BaseModel):
    """A prompt's observability view over a window: overall, per version, and per feature.

    ``since`` is the inclusive cutoff the window resolved to (echoed so a caller can see exactly
    what range produced these numbers).
    """

    name: str
    prompt_id: uuid.UUID
    window: str
    since: datetime
    overall: MetricsBlockDTO
    by_version: list[VersionMetricsDTO]
    by_source: list[SourceCostDTO]


class MetricsBucketDTO(BaseModel):
    """One time bucket of the series. Empty buckets are present (gap-filled): ``request_count`` is a
    real ``0`` while ``error_rate``/``p95_ms``/``cost_usd``/``quality`` are null when the bucket had
    no traffic / no eval. ``cost_usd`` is an exact decimal *string* for the same money-safety reason
    as :class:`MetricsBlockDTO`.
    """

    bucket_start: datetime
    request_count: int
    error_rate: float | None
    p95_ms: float | None
    cost_usd: str | None
    quality: float | None


class PromptTimeseriesResponse(BaseModel):
    """A prompt's metrics bucketed over time. ``interval`` echoes the bucket size used (it defaults
    from the window when the caller doesn't pin one), ``since`` the inclusive window cutoff, and
    ``version`` the version the series was scoped to (null = the whole prompt).
    """

    name: str
    prompt_id: uuid.UUID
    window: str
    interval: str
    since: datetime
    version: int | None
    buckets: list[MetricsBucketDTO]


class PromptRollupDTO(BaseModel):
    """One prompt's row in the fleet overview: window traffic, latest quality, attention flags.

    ``cost_usd`` is the exact decimal string (money-safety, as elsewhere). ``attention`` holds the
    rule *keys* that fired (e.g. ``"high_error_rate"``) — the UI owns the wording and badge styling.
    """

    name: str
    latest_version: int | None
    request_count: int
    error_rate: float | None
    p95_ms: float | None
    cost_usd: str | None
    quality: float | None
    attention: list[str]


class OverviewResponse(BaseModel):
    """The fleet landing page: window echo, totals, a gap-filled trend, and per-prompt rows."""

    window: str
    interval: str
    since: datetime
    totals: MetricsBlockDTO
    trend: list[MetricsBucketDTO]
    prompts: list[PromptRollupDTO]


class AlertDTO(BaseModel):
    """One threshold breach. ``observed`` is what was measured, ``threshold`` the line crossed."""

    kind: str
    scope: str
    observed: float
    threshold: float
    message: str


class AlertsResponse(BaseModel):
    """The drift/regression alerts currently firing for a prompt over a window (empty = healthy)."""

    name: str
    window: str
    alerts: list[AlertDTO]


class ThresholdDTO(BaseModel):
    """One configured alert threshold, self-describing so the UI renders it generically.

    ``unit`` tells the client which formatter to apply rather than baking that into the API:
    ``score`` (a 0-1 quality value, e.g. 0.70), ``ratio`` (a 0-1 fraction shown as a percentage,
    e.g. 0.10 -> 10%), ``usd`` (a dollar amount), ``count`` (an integer). ``value`` is always a
    number on the wire; the ``count`` unit signals the UI should drop the decimal.
    """

    key: str
    label: str
    value: float
    unit: Literal["score", "ratio", "usd", "count"]


class AlertPolicyResponse(BaseModel):
    """The active drift-alert thresholds, derived from process config (ADR 0026).

    Deliberately a flat, *global* list with no per-prompt identity (no name/id/scope): v0.1 has no
    ``alert_policies`` table and ``PUT /prompts/{name}/alert-policy`` is deferred, so the shape must
    not imply per-prompt persistence. Per-prompt overrides (phase 2) would be a separate endpoint
    returning a superset of this list plus provenance.
    """

    thresholds: list[ThresholdDTO]


class QueueDepthDTO(BaseModel):
    """Pending (not-yet-delivered) message count for one Celery broker queue."""

    name: str
    depth: int


class QueueHealthResponse(BaseModel):
    """Celery queue/worker health for the admin ops surface (Sprint 29 T3).

    ``available`` is False when the broker can't be reached — every count is then null (the endpoint
    degrades, it never 500s). ``workers``/``active`` are null when the broker was up but worker
    inspection failed; ``queued`` is the total backlog across ``queues``.
    """

    available: bool
    workers: int | None
    active: int | None
    queued: int | None
    queues: list[QueueDepthDTO] | None


class CacheStatsResponse(BaseModel):
    """Render-cache hit-rate for one prompt (Sprint 29 T4).

    Cumulative since the API process started and per-process (each worker counts its own), so it's
    an operability signal, not an accounting figure. ``hit_rate`` is null when there's been no
    render traffic yet (``total == 0``); ``ttl_seconds`` is the cache TTL, for staleness context.
    """

    prompt: str
    hits: int
    misses: int
    total: int
    hit_rate: float | None
    ttl_seconds: int


class TraceIngestRequest(BaseModel):
    """Body for ``POST /traces`` — one emitted execution reported by an SDK client.

    This is the *edge* contract: it validates the incoming JSON, then the router converts
    it to a domain ``TraceEvent`` and enqueues it. ``id`` is optional — the client may send
    a UUID it generated (so a client-side retry is idempotent) or let the server mint one.
    ``cost_usd`` is deliberately absent: cost is computed server-side from the pricing table,
    never trusted from the caller.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=255)
    status: Literal["ok", "error"]
    prompt_id: uuid.UUID | None = None
    prompt_version_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=32)
    provider: str | None = Field(default=None, max_length=64)
    provider_model: str | None = Field(default=None, max_length=255)
    input: str | None = None
    output: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = Field(default=None, max_length=255)


class TraceAccepted(BaseModel):
    """Response to an accepted trace: the id it was (or will be) stored under."""

    trace_id: uuid.UUID


# --- Datasets / golden sets + the promotion gate (Sprint 11) ---------------------


class DatasetItemDTO(BaseModel):
    """One golden-set case: an input and (optionally) the reference answer to grade against."""

    input: str = Field(min_length=1)
    reference: str | None = None
    metadata: dict[str, Any] | None = None


class DatasetCreate(BaseModel):
    """Request body for creating a golden set with its cases."""

    name: str = Field(min_length=1, max_length=255, pattern=_NAME_PATTERN)
    description: str | None = None
    # A golden set with nothing to grade can't gate anything — require at least one case.
    items: list[DatasetItemDTO] = Field(min_length=1)


class DatasetUpdate(BaseModel):
    """Request body for PUT — the full desired state of a golden set's cases (ADR 0024).

    The name is immutable and taken from the path, not the body. ``items`` replaces the existing
    cases wholesale, so it carries the complete list; at least one, same as create — an empty
    golden set can't gate anything.
    """

    description: str | None = None
    items: list[DatasetItemDTO] = Field(min_length=1)


class DatasetRead(BaseModel):
    """A golden set as returned to clients (item count, not the full case list)."""

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    item_count: int


class DatasetDetail(DatasetRead):
    """A single golden set *with* its cases — what the editor prefills from on edit.

    The list view stays lean (``DatasetRead``, count only); only the detail read carries the case
    bodies, since that's the one place a client needs them.
    """

    items: list[DatasetItemDTO]


class GoldenSetAttach(BaseModel):
    """Request body for pointing a prompt at the golden set it must clear to be promoted."""

    dataset: str = Field(min_length=1, max_length=255)


class EvalRunAccepted(BaseModel):
    """Response to a manually triggered eval: the run id created (status starts ``pending``)."""

    eval_run_id: uuid.UUID
    status: str


class EvalStatusResponse(BaseModel):
    """A version's derived eval state (see EvalStatusView) plus the latest run's summary."""

    prompt: str
    version_number: int
    prompt_version_id: uuid.UUID
    status: str
    latest_run_id: uuid.UUID | None
    summary: dict[str, Any] | None


class EvalRunSummary(BaseModel):
    """One historical eval run, for the per-version run-history list (newest first).

    The ``summary`` is the run's own aggregate rollup (same shape as
    ``EvalStatusResponse.summary``) — present once the run completes, ``None`` while it is
    still pending/running or if it failed. ``scorers`` is the scorer *names* this run graded
    with, lifted out of the stored ``scorer_config`` so the list needn't unpack the config.
    """

    id: uuid.UUID
    status: str
    scorers: list[str]
    created_at: datetime
    completed_at: datetime | None
    summary: dict[str, Any] | None


class ScanAccepted(BaseModel):
    """Response to a manually triggered security scan: the scan id created (status ``pending``)."""

    security_scan_id: uuid.UUID
    status: str


class ScanStatusResponse(BaseModel):
    """A version's derived scan state (see ScanStatusView): risk level + the findings list."""

    prompt: str
    version_number: int
    prompt_version_id: uuid.UUID
    status: str
    latest_scan_id: uuid.UUID | None
    risk_level: str | None
    findings: list[dict[str, Any]] | None


class ScanRunSummary(BaseModel):
    """One historical security scan, for the per-version scan-history list (newest first).

    Carries the full ``findings`` list (same shape as ``ScanStatusResponse.findings``) so the
    drill-in into a scan needs no second call — the list's finding *count* is derived from it.
    ``findings`` / ``risk_level`` are ``None`` while the scan is pending/running or if it failed.
    """

    id: uuid.UUID
    status: str
    scanners: list[str]
    risk_level: str | None
    findings: list[dict[str, Any]] | None
    created_at: datetime
    completed_at: datetime | None


class TraceSummary(BaseModel):
    """One execution in the trace list (newest first) — the lean row, no rendered text.

    Deliberately excludes ``input``/``output`` (the heavy columns): the list shows cost/latency/
    status/model only, and the full rendered prompt + output load on the single-trace detail.
    ``cost_usd`` is an exact decimal string (never a float) for the same money-precision reason as
    the metrics endpoints.
    """

    id: uuid.UUID
    prompt_id: uuid.UUID | None
    prompt_version_id: uuid.UUID | None
    source: str | None
    provider: str | None
    model: str
    cost_usd: str | None
    latency_ms: int | None
    status: str
    created_at: datetime


class TraceDetail(TraceSummary):
    """One execution in full — the debugging drill-down: the rendered prompt + model output.

    Extends the summary with everything a single trace carries: the rendered ``input`` and model
    ``output`` (either may be absent if the emitter omitted it), token counts, the served model,
    the failure type on an errored call, and the correlation ``request_id``.
    """

    provider_model: str | None
    request_id: str | None
    input: str | None
    output: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    error_type: str | None


class RenderResponse(BaseModel):
    """A finished prompt plus the version's model config and output schema.

    The ``prompt_id`` / ``prompt_version_id`` / ``version_number`` identify the exact
    version that produced this render, so a caller can attribute a later trace back to
    it (the Phase 7 cost/latency/quality-per-version linkage).
    """

    prompt: str
    model_settings: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    prompt_id: uuid.UUID
    prompt_version_id: uuid.UUID
    version_number: int


# --- Human auth DTOs (Sprint 13 / Phase 11, ADR 0018). The boundary shapes for the JWT login
# path; the static API-key path carries no body so it has no DTO.


class LoginRequest(BaseModel):
    """Credentials posted to ``POST /auth/login``."""

    # EmailStr would add a dependency (email-validator); a plain bounded string is enough — the
    # service normalises it and the only thing that matters is matching the stored value.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    """The access + refresh pair returned by login. ``token_type`` is the OAuth2 bearer scheme."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class RefreshRequest(BaseModel):
    """A refresh token exchanged at ``POST /auth/refresh`` for a new access token."""

    refresh_token: str = Field(min_length=1)


class AccessTokenResponse(BaseModel):
    """A single fresh access token (the refresh endpoint's reply — no new refresh token)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserCreate(BaseModel):
    """Request body for the admin-only ``POST /auth/users``."""

    email: str = Field(min_length=3, max_length=320)
    # A minimum length is the one password rule we enforce at the boundary; richer policy is
    # out of scope for v0.1. The 1024 cap guards against a huge-input DoS (bcrypt only reads 72).
    password: str = Field(min_length=8, max_length=1024)
    role: Literal["admin", "editor"] = "editor"


class UserRead(BaseModel):
    """A user as returned to clients — never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """Request body for the admin-only ``PATCH /auth/users/{id}``: role and/or active flag.

    Both fields are optional so a caller can change just one, but at least one must be present —
    an empty patch is a 422, not a silent no-op. Email and password are deliberately *not*
    editable here (out of scope for v0.1's admin surface).
    """

    role: Literal["admin", "editor"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "UserUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("provide at least one of: role, is_active")
        return self


class AuditEventResponse(BaseModel):
    """One audited action as returned by the Activity page."""

    id: str
    actor: str
    action: str
    target: str
    timestamp: str


class AuditLogPage(BaseModel):
    """Paginated audit log — newest events first."""

    events: list[AuditEventResponse]
    total: int
