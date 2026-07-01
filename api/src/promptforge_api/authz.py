"""FastAPI dependencies for the human-auth path: identify the caller, then gate by role.

Separated from :mod:`promptforge_api.tokens` (pure JWT) and :mod:`promptforge_api.services.auth`
(use-cases) because these are *HTTP wiring* — they read the ``Authorization`` header, talk to the
DB, and raise ``HTTPException``. Task 3 (authz on the registry) imports the role guards here.

**Open when unconfigured.** With no ``jwt_secret`` set, the gate is a no-op — exactly like the
API-key and Redis paths — so a bare local run and the test suite need no tokens. Configure the
secret in production and every protected endpoint then demands a valid access token.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from promptforge_api.config import Settings, get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.db.user_models import User
from promptforge_api.repositories.users import UserRepository
from promptforge_api.services.auth import AuthService
from promptforge_api.tokens import InvalidTokenError, decode_token

# auto_error=False: we decide what a missing credential means (it depends on whether auth is
# configured), rather than letting FastAPI raise a blanket 403. The scheme still shows the
# "Authorize" button in /docs.
_bearer = HTTPBearer(auto_error=False, description="Bearer <access token> from POST /auth/login")

_CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
_SessionDep = Annotated[Session, Depends(get_session)]
_SettingsDep = Annotated[Settings, Depends(get_settings)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="missing or invalid access token",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: _CredentialsDep,
    session: _SessionDep,
    settings: _SettingsDep,
) -> User | None:
    """Resolve the access token to a live user, or ``None`` when auth is disabled.

    Returns ``None`` only when no ``jwt_secret`` is configured (auth off). When auth is on, a
    missing/invalid/expired token, or a token for a deleted or disabled user, raises **401** —
    it never falls through to ``None``.
    """
    if not settings.jwt_secret:
        return None  # auth disabled — anonymous caller

    if credentials is None:
        raise _UNAUTHENTICATED
    try:
        claims = decode_token(
            credentials.credentials, secret=settings.jwt_secret, expected_type="access"
        )
    except InvalidTokenError as exc:
        raise _UNAUTHENTICATED from exc

    service = AuthService(
        UserRepository(session),
        jwt_secret=settings.jwt_secret,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )
    user = service.get_user(claims.subject)
    # Reject a deleted/disabled user, or a **revoked** token whose stamped version no longer
    # matches the user's current token_version (ADR 0029). The user load already happened for the
    # is_active check, so the version comparison is free.
    if user is None or not user.is_active or claims.token_version != user.token_version:
        raise _UNAUTHENTICATED
    return user


CurrentUserDep = Annotated["User | None", Depends(get_current_user)]


def audit_actor(user: User | None) -> str:
    """The audit trail's "who": the authenticated user's email, or ``system`` when auth is off.

    Every audited action — version/user create, golden-set attach, and label moves/promotions —
    attributes to a real human via the ``require_*`` dependency's returned ``User`` (ADR 0028). A
    single convention keeps the Activity feed consistent.
    """
    return user.email if user is not None else "system"


def _require_role(*allowed: str):  # type: ignore[no-untyped-def]
    """Build a dependency that admits only the given roles (and is a no-op when auth is off)."""

    def guard(user: CurrentUserDep) -> User | None:
        if user is None:
            return None  # auth disabled — allow through
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of: {', '.join(allowed)}",
            )
        return user

    return guard


# admin may manage users + promote; editor (or admin) may author prompts/versions. Used as
# route dependencies in the auth router (admin) and the registry routers in Task 3.
require_admin = _require_role("admin")
require_editor = _require_role("admin", "editor")
