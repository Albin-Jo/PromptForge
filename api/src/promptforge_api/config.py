"""Application configuration, loaded from the environment (12-factor).

All runtime config lives in one typed object that is populated from environment
variables (prefixed ``PROMPTFORGE_``) or, for local development, a gitignored
``.env`` file. Invalid or missing values fail loudly at startup rather than at
request time.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from promptforge_api import __version__


class Settings(BaseSettings):
    """Process-wide configuration, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="PROMPTFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "promptforge-api"
    environment: Literal["local", "ci", "prod"] = "local"
    log_level: str = "INFO"
    version: str = __version__

    # Synchronous psycopg DSN (see ADR 0003). The compose stack injects this as
    # PROMPTFORGE_DATABASE_URL; this default is the bare host-run fallback and matches the
    # *non-default* host port published in docker-compose.yml (5435, chosen to avoid a
    # native Postgres on 5433 and another local stack on 5434). A real host run should set
    # PROMPTFORGE_DATABASE_URL in .env — see .env.example.
    database_url: str = "postgresql+psycopg://promptforge:promptforge_local_dev@localhost:5435/promptforge"

    # Celery transport for off-request-path work (Sprint 6). The API is a *producer*:
    # it enqueues tasks by name and reads results by job id, but never runs them. These
    # point at the same Redis as the worker (broker DB 1, result backend DB 2 — kept
    # separate from the cache's DB 0). The compose stack injects the in-network URLs.
    celery_broker_url: str = "redis://localhost:6381/1"
    celery_result_backend: str = "redis://localhost:6381/2"

    # Redis is an optional read-through accelerator for hot prompt fetches, never a hard
    # dependency: when unset the API serves straight from Postgres. The compose stack
    # injects PROMPTFORGE_REDIS_URL; left None so tests and bare local runs need no Redis.
    redis_url: str | None = None
    # How long a rendered prompt stays in the server cache. Short because a label is
    # mutable — this bounds post-deploy staleness (the SDK tolerates it on a floating
    # fetch). TTL-only invalidation for v0.1; explicit bust-on-deploy is a later option.
    render_cache_ttl_seconds: int = 30

    # Optional override path for the model pricing table (Phase 7). Unset → the table bundled
    # in the package (pricing.json) is used; set it to point cost computation at an updated
    # file without a rebuild (config-driven pricing — ADR/build plan). See pricing.py.
    pricing_file: str | None = None

    # --- Drift / regression alert thresholds (Phase 7). These define when the live
    # observability data is "bad enough" to flag. Observational only: a breach is surfaced via
    # GET /prompts/{name}/alerts + a structured warning log — never delivered (email/webhook) or
    # persisted/deduped (that, and promotion gating, is later work). All overridable via env.
    alert_min_quality: float = 0.7  # per-version eval mean below this → alert
    alert_max_error_rate: float = 0.1  # overall trace error rate above this → alert
    alert_max_cost_per_request_usd: Decimal = Decimal("0.05")  # overall avg cost/call above → alert
    alert_max_quality_drop: float = 0.1  # a version's quality this far below the prior one → alert
    # Floor on trace volume before the noisy (traffic-derived) signals fire, so a handful of
    # calls can't trip a false alert. Does not gate quality, which comes from a deliberate eval.
    alert_min_requests: int = 20

    # --- Promotion gate ("CI for prompts", Sprint 11 / Phase 8). Moving the *gated label*
    # to a version is a deployment, and these decide when that's allowed. Unlike the alert
    # thresholds above (observational), a breach here *blocks* the promotion. All env-overridable.
    # The label whose moves are gated; other labels (e.g. "staging") move freely so a candidate
    # can be parked for evaluation before it's eligible for production.
    promotion_gated_label: str = "production"
    # Absolute floor: a candidate's per-scorer pass-rate must be at least this to be promotable.
    # Separate from alert_min_quality (which judges live traffic) so the gate can be tuned apart.
    promotion_min_quality: float = 0.7
    # Relative bar: how far a candidate's pass-rate may fall below the current production
    # version's, per scorer, before it counts as a regression and is refused. Tighter than the
    # observational alert drop because this one blocks a ship.
    promotion_max_quality_drop: float = 0.05
    # The (noisy) regression check is only applied when the golden set has at least this many
    # items — below it, a one-item flip is a huge percentage swing, so we fall back to the
    # absolute floor only and record that the regression check was skipped (ADR 0016).
    promotion_min_dataset_size: int = 5
    # Optional outbound webhook fired on every gated-label decision (promoted | blocked).
    # None = disabled (the decision is still logged + audited). Delivery is async + retried via
    # the worker; if a secret is set, the body is signed (HMAC-SHA256) so the receiver can verify.
    promotion_webhook_url: str | None = None
    promotion_webhook_secret: str | None = None

    # --- Security scan gate (Sprint 12 / Phase 10). Every version is scanned on save for
    # injection/secrets/PII/jailbreaks; this decides whether a finding *blocks* promotion of the
    # gated label or is only advisory. Default "warn": findings are recorded and visible (GET
    # .../scan) and logged, but never block — the safe default while false-positive tuning settles
    # (ADR 0017). "block": refuse promotion when the candidate's latest completed scan risk level
    # is at or above scan_gate_block_severity. Reuses the same gated label as the eval gate.
    scan_gate_mode: Literal["warn", "block"] = "warn"
    scan_gate_block_severity: Literal["low", "medium", "high"] = "high"

    # Static API keys that gate the SDK fetch endpoint (Sprint 5). Multiple keys allow
    # rotation. Empty = auth disabled (the endpoint is open) — convenient for local/dev;
    # set keys in production. This is a deliberately minimal gate, NOT the user/role auth
    # system (Sprint 13). ``NoDecode`` stops pydantic-settings from JSON-parsing the env
    # value so the validator below can read a plain comma-separated string.
    api_keys: Annotated[list[str], NoDecode] = []

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Parse ``PROMPTFORGE_API_KEYS="k1,k2"`` into a list; pass lists through as-is."""
        if isinstance(value, str):
            return [key.strip() for key in value.split(",") if key.strip()]
        return value

    # --- Human user auth (Sprint 13 / Phase 11, ADR 0018). Distinct from the static API keys
    # above: those are machine credentials for the SDK; these back the JWT login path for people.
    # Secret used to sign/verify HS256 JWTs. None = user auth is unconfigured: login refuses with
    # 503 (and a startup warning is logged), mirroring the api_keys fail-open posture — a bare
    # local run needs neither. MUST be set (a long random string) in any deployment with users.
    jwt_secret: str | None = None
    # Access tokens are short-lived (exposure window); refresh tokens are long-lived and only
    # mint new access tokens. Both are revocable via a per-user token_version claim (ADR 0029,
    # superseding the "non-revocable" part of ADR 0018): bumping the user's token_version
    # invalidates every outstanding token; the 7-day TTL is the fallback bound. Env-overridable.
    access_token_ttl_seconds: int = 1800  # 30 minutes
    refresh_token_ttl_seconds: int = 604800  # 7 days

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def _require_strong_secret(cls, value: str | None) -> str | None:
        """Fail fast on a weak signing key (RFC 7518 §3.2: ≥32 bytes for HS256).

        A short ``jwt_secret`` makes tokens cheap to forge; PyJWT only *warns* at runtime, so we
        reject it at startup instead. ``None`` (auth disabled) is allowed.
        """
        if value is not None and len(value.encode("utf-8")) < 32:
            raise ValueError("jwt_secret must be at least 32 bytes (HS256 minimum)")
        return value

    # Optional bootstrap admin, upserted at startup when both are set, so a fresh deployment has
    # exactly one way in before any user exists (there is no open signup). Leave unset locally.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- API hardening (Sprint 13 / Phase 11). Browser origins allowed to call the API
    # cross-origin (the React UI's origin, Sprints 14-16). Empty = no cross-origin requests
    # allowed (the safe default); the SDK and server-to-server callers are unaffected since CORS
    # is a browser-enforced policy. Comma-separated, parsed like ``api_keys``. We never combine
    # this with credentials (we use bearer tokens in headers, not cookies), so a wildcard here
    # would not be a credential-leak footgun — but we still default to an explicit allowlist.
    cors_allow_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Parse ``PROMPTFORGE_CORS_ALLOW_ORIGINS="https://a,https://b"`` into a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- LLM gateway models (Sprint 28). The model identifiers the playground's model picker
    # offers via ``GET /models``. Non-secret, so that read has no role gate. Comma-separated and
    # parsed exactly like ``api_keys``/``cors_allow_origins``. Empty = unconfigured: the endpoint
    # returns ``[]`` and the UI falls back to a free-text model field so local/dev runs still work.
    gateway_models: Annotated[list[str], NoDecode] = []

    @field_validator("gateway_models", mode="before")
    @classmethod
    def _split_models(cls, value: object) -> object:
        """Parse ``PROMPTFORGE_GATEWAY_MODELS="openai/gpt-4o-mini,anthropic/..."`` into a list."""
        if isinstance(value, str):
            return [model.strip() for model in value.split(",") if model.strip()]
        return value

    # --- Rate limiting (Sprint 13 / Phase 11). A fixed-window counter per *principal* (the API
    # key, else the authenticated user, else the client IP). 0 = disabled (the default): no limiter
    # runs. When > 0 the cap is enforced: with a redis_url it's shared across processes; WITHOUT
    # Redis it falls back to a per-process in-memory limiter (logged) so enabling the limit is never
    # a silent no-op. Either way it fails open on error. Login is not exempt, so setting this also
    # rate-limits credential brute-force — strongly recommended in any real deployment.
    rate_limit_requests: int = 0
    rate_limit_window_seconds: int = 60
    # Whether to trust the client IP in the X-Forwarded-For header for rate-limit keying. Default
    # False: XFF is caller-spoofable, so we only honor it when the API sits behind a trusted proxy
    # that sets it (then anonymous callers are keyed by real IP, not the proxy's single address).
    rate_limit_trust_forwarded: bool = False

    # Largest request body we accept, in bytes (default 1 MiB). A request whose Content-Length
    # exceeds this is rejected with 413 before the body is read — a cheap guard against a
    # memory-exhaustion DoS via a giant payload.
    max_request_bytes: int = 1_048_576


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    return Settings()
