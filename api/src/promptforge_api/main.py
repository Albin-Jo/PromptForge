"""FastAPI application factory.

``create_app`` builds a fully wired app (logging, middleware, routers) so tests
can construct an isolated instance, while ``app`` is the module-level instance
that ``uvicorn promptforge_api.main:app`` serves.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from promptforge_api.config import Settings, get_settings
from promptforge_api.db.engine import SessionLocal
from promptforge_api.errors import register_error_handlers
from promptforge_api.logging_config import configure_logging
from promptforge_api.middleware import (
    REQUEST_ID_HEADER,
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from promptforge_api.repositories.users import UserRepository
from promptforge_api.routers import (
    alerts,
    audit,
    auth,
    blocks,
    datasets,
    gateway,
    health,
    metrics,
    overview,
    prompts,
    traces,
)
from promptforge_api.services.auth import AuthService, UserAlreadyExistsError

_logger = structlog.get_logger(__name__)

# The OpenAPI description rendered at /docs and /redoc. Markdown — it's the first thing a
# stranger reads when they open the API, so it states what the platform is and the core flow.
_API_DESCRIPTION = """\
Manage LLM prompts as **versioned, tested, observable** production assets.

- **Registry** — create prompts, append immutable versions, render a version's template.
- **Deployments** — point a label (`production`/`staging`) at a version; moving it is a deploy.
- **Gateway** — call any model provider through one streaming interface (via LiteLLM).
- **Observability** — record a trace per execution, then query latency percentiles, spend, error
  rate, and per-version quality, with threshold-based drift alerts.

**Core flow:** create a prompt → render the version a label points at (via the SDK) → call the
model → report a trace → read cost/latency/quality per version. Every request carries an
`X-Request-ID` correlation id (echoed back) threaded through logs and background tasks.
"""

# Per-tag blurbs so the grouped endpoint list at /docs explains itself.
_OPENAPI_TAGS = [
    {"name": "prompts", "description": "Registry: prompts, immutable versions, labels, rendering."},
    {"name": "blocks", "description": "Reusable, typed, versioned fragments prompts compose from."},
    {"name": "datasets", "description": "Golden sets the promotion gate evaluates against."},
    {"name": "gateway", "description": "Provider-agnostic streaming completions (LiteLLM-backed)."},
    {"name": "traces", "description": "Ingest one execution; persisted async, off the hot path."},
    {"name": "metrics", "description": "Per-prompt latency/cost/error/quality + drift alerts."},
    {"name": "overview", "description": "Fleet-wide totals, trend, and a needs-attention rollup."},
    {"name": "auth", "description": "Human login: JWT access/refresh tokens, current user, users."},
    {"name": "health", "description": "Liveness."},
]


def _bootstrap_admin(settings: Settings) -> None:
    """Upsert the configured bootstrap admin so a fresh deployment has one way in.

    No-op unless both ``bootstrap_admin_email`` and ``bootstrap_admin_password`` are set, so
    local runs and the test suite (which set neither) never touch the database here. An existing
    admin is left untouched — we never clobber a rotated password.
    """
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        return

    session = SessionLocal()
    try:
        service = AuthService(
            UserRepository(session),
            # The secret is unused by create_user; "" is a safe placeholder when auth has no
            # signing key yet (the admin row is created; they can log in once jwt_secret is set).
            jwt_secret=settings.jwt_secret or "",
            access_ttl_seconds=settings.access_token_ttl_seconds,
            refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        )
        user = service.create_user(
            settings.bootstrap_admin_email, settings.bootstrap_admin_password, role="admin"
        )
        session.commit()
        _logger.info("bootstrap_admin_created", email=user.email)
    except UserAlreadyExistsError:
        # Already provisioned — never clobber a rotated password.
        session.rollback()
        _logger.info("bootstrap_admin_exists")
    except Exception:
        session.rollback()
        _logger.exception("bootstrap_admin_failed")
    finally:
        session.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(settings)

    if not settings.api_keys:
        # Surface the fail-open auth state once at startup, not per request.
        _logger.warning("api_key_auth_disabled", reason="no api_keys configured")
    if not settings.jwt_secret:
        # Same posture for the human-auth path: open until a signing secret is set.
        _logger.warning("user_auth_disabled", reason="no jwt_secret configured")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _bootstrap_admin(settings)
        yield

    app = FastAPI(
        title="PromptForge API",
        version=settings.version,
        summary="Versioned, tested, observable LLM prompts.",
        description=_API_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        license_info={"name": "MIT", "url": "https://opensource.org/license/mit"},
        contact={"name": "PromptForge", "url": "https://github.com/Albin-Jo/PromptForge"},
        lifespan=lifespan,
    )
    # Middleware runs in REVERSE order of registration, so the request-processing order is the
    # reverse of the calls below: CORS (outermost, answers preflight) → security headers → rate
    # limit → size limit → request id (innermost, wraps the app). Security headers sit outside the
    # limiters so even a 429/413 carries them; request id stays innermost so every app log line has
    # the correlation id.
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        # We use bearer tokens in the Authorization header, not cookies, so credentialed CORS is
        # unnecessary; keeping it False avoids the wildcard-with-credentials class of mistakes.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(audit.router)
    app.include_router(prompts.router)
    app.include_router(blocks.router)
    app.include_router(datasets.router)
    app.include_router(gateway.router)
    app.include_router(traces.router)
    app.include_router(metrics.router)
    app.include_router(overview.router)
    app.include_router(alerts.router)
    app.include_router(auth.router)
    return app


app = create_app()
