"""HTTP layer for human auth: login, refresh, current user, and admin-only user creation.

Translation only — the credential checks, hashing, and token minting live in
:mod:`promptforge_api.services.auth` (ADR 0018). Handlers are ``def`` (threadpool) so the sync DB
session never blocks the event loop (ADR 0003).

These endpoints need a configured ``jwt_secret`` to mint/verify tokens; without one the service
assembly returns **503** ("auth not configured"), consistent with the open-when-unconfigured
posture used elsewhere — the difference is you can't *issue* a token without a secret to sign it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from promptforge_api.authz import CurrentUserDep, audit_actor, require_admin
from promptforge_api.config import Settings, get_settings
from promptforge_api.db.engine import get_session
from promptforge_api.db.user_models import User
from promptforge_api.repositories.audit import AuditRepository
from promptforge_api.repositories.users import UserRepository
from promptforge_api.schemas import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from promptforge_api.services.auth import AuthService, InvalidCredentialsError, InvalidTokenError

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    """Assemble the auth service, refusing (503) if no signing secret is configured."""
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="user authentication is not configured",
        )
    return AuthService(
        UserRepository(session),
        jwt_secret=settings.jwt_secret,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        audits=AuditRepository(session),
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, service: AuthServiceDep) -> TokenResponse:
    """Exchange email + password for an access + refresh token pair."""
    try:
        tokens = service.login(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise _INVALID_CREDENTIALS from exc
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(payload: RefreshRequest, service: AuthServiceDep) -> AccessTokenResponse:
    """Exchange a valid refresh token for a fresh access token."""
    try:
        access_token = service.refresh(payload.refresh_token)
    except (InvalidTokenError, InvalidCredentialsError) as exc:
        raise _INVALID_CREDENTIALS from exc
    return AccessTokenResponse(access_token=access_token)


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUserDep) -> User:
    """Return the authenticated user. 401 when auth is on and no valid token is presented."""
    if current_user is None:
        # Only reachable when auth is disabled (no jwt_secret): there is no "me".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user authentication is not configured",
        )
    return current_user


@router.get(
    "/users",
    response_model=list[UserRead],
    dependencies=[Depends(require_admin)],
)
def list_users(service: AuthServiceDep) -> list[User]:
    """List all users (admin only), newest first. Never includes password hashes (UserRead)."""
    return service.list_users()


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    service: AuthServiceDep,
    actor_user: Annotated[User | None, Depends(require_admin)],
) -> User:
    """Create a user (admin only). Email is normalised; the password is stored hashed."""
    return service.create_user(
        payload.email, payload.password, payload.role, actor=audit_actor(actor_user)
    )


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    service: AuthServiceDep,
    actor_user: Annotated[User | None, Depends(require_admin)],
) -> User:
    """Change a user's role and/or active flag (admin only).

    404 for an unknown id; **409** if the change would remove the last active admin (the
    self-lockout guard, ADR 0029). A role change or a deactivation revokes the user's outstanding
    tokens (their next request/refresh 401s and they must log in again).
    """
    return service.update_user(
        user_id,
        role=payload.role,
        is_active=payload.is_active,
        actor=audit_actor(actor_user),
    )


@router.post("/users/{user_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_tokens(
    user_id: uuid.UUID,
    service: AuthServiceDep,
    actor_user: Annotated[User | None, Depends(require_admin)],
) -> None:
    """Revoke all of a user's outstanding tokens (admin only) — "log them out everywhere".

    A leaked-credential response that leaves the account's role and active state untouched
    (ADR 0029). 404 for an unknown id.
    """
    service.revoke_tokens(user_id, actor=audit_actor(actor_user))
