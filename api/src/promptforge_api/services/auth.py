"""Authentication use-cases: log in, refresh, and create users (Sprint 13 / Phase 11).

Holds the *what* of human auth — verify a password, mint a token pair, exchange a refresh token,
create a user — speaking plain arguments and ORM entities, never Pydantic or HTTP (CLAUDE.md /
ADR 0003). The JWT secret and TTLs are injected at construction (read from settings in the router
assembly) so the service stays config-agnostic and unit-testable.

Two security choices live here, not in the router:

* **No user enumeration.** A wrong password and an unknown email raise the *same*
  :class:`InvalidCredentialsError`, and a missing user still triggers a dummy hash verify so the
  response time doesn't reveal whether the email exists.
* **Refresh re-checks the user.** Exchanging a refresh token reloads the user and refuses a
  disabled account, so deactivating a user takes effect on their next refresh even though the
  tokens themselves are stateless (ADR 0018).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from promptforge_api.db.user_models import User
from promptforge_api.repositories.audit import AuditRepository
from promptforge_api.repositories.users import UserRepository
from promptforge_api.security import hash_password, verify_password
from promptforge_api.tokens import InvalidTokenError, create_token, decode_token


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A throwaway bcrypt hash to verify against when no user matches, so authentication takes
    roughly the same time whether or not the email exists (defeats timing-based enumeration).
    Computed lazily and cached so importing this module stays cheap."""
    return hash_password("dummy-password-for-constant-time-compare")


class InvalidCredentialsError(Exception):
    """Raised when an email/password pair (or a refresh token's user) is not valid."""

    def __init__(self) -> None:
        super().__init__("invalid email or password")


class UserAlreadyExistsError(Exception):
    """Raised when creating a user whose email is already taken."""

    def __init__(self, email: str) -> None:
        super().__init__(f"user '{email}' already exists")
        self.email = email


class UserNotFoundError(Exception):
    """Raised when updating/revoking a user id that doesn't exist (mapped to 404)."""

    def __init__(self, user_id: uuid.UUID) -> None:
        super().__init__(f"user '{user_id}' not found")
        self.user_id = user_id


class LastAdminError(Exception):
    """Raised when a change would leave the platform with no active admin (mapped to 409).

    The self-lockout guard (ADR 0029): demoting or deactivating the *last* active admin is
    refused, so an admin can't accidentally lock everyone out of user management. The rule is
    "at least one active admin must remain" — an admin may still demote/disable *other* admins.
    """

    def __init__(self) -> None:
        super().__init__("cannot remove the last active admin")


@dataclass(frozen=True)
class TokenPair:
    """The result of a successful login: a short access token + a long refresh token."""

    access_token: str
    refresh_token: str


def _normalise_email(email: str) -> str:
    """Lower-case and trim so uniqueness and lookups are case-insensitive."""
    return email.strip().lower()


def _describe_update(user: User, role: str | None, is_active: bool | None) -> str:
    """Human-readable audit target for a user update, naming only the fields that changed."""
    changes = []
    if role is not None:
        changes.append(f"role={role}")
    if is_active is not None:
        changes.append("active" if is_active else "inactive")
    return f"user:{user.email} ({', '.join(changes)})"


class AuthService:
    """Use-cases for human auth: login, refresh, create user, load current user."""

    def __init__(
        self,
        repository: UserRepository,
        *,
        jwt_secret: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        audits: AuditRepository | None = None,
    ) -> None:
        self._repository = repository
        self._jwt_secret = jwt_secret
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds
        # Optional audit sink: with it, user creation appends an audit_events row (ADR 0028).
        # Without it (login/refresh/current-user paths and unit tests), it's a no-op.
        self._audits = audits

    def authenticate(self, email: str, password: str) -> User:
        """Return the active user for valid credentials, else raise InvalidCredentialsError."""
        user = self._repository.get_by_email(_normalise_email(email))
        if user is None:
            # Spend the same work as a real verify so timing doesn't leak existence.
            verify_password(password, _dummy_hash())
            raise InvalidCredentialsError
        # Always verify (even for a disabled user) before deciding, so response time doesn't
        # distinguish "disabled account" from "active account, wrong password".
        password_ok = verify_password(password, user.password_hash)
        if not user.is_active or not password_ok:
            raise InvalidCredentialsError
        return user

    def issue_tokens(self, user: User) -> TokenPair:
        """Mint an access + refresh token pair for an authenticated user."""
        access = create_token(
            subject=user.id,
            role=user.role,
            token_type="access",
            secret=self._jwt_secret,
            ttl_seconds=self._access_ttl,
            token_version=user.token_version,
        )
        refresh = create_token(
            subject=user.id,
            role=user.role,
            token_type="refresh",
            secret=self._jwt_secret,
            ttl_seconds=self._refresh_ttl,
            token_version=user.token_version,
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    def login(self, email: str, password: str) -> TokenPair:
        """Authenticate and issue a token pair in one step."""
        return self.issue_tokens(self.authenticate(email, password))

    def refresh(self, refresh_token: str) -> str:
        """Exchange a valid refresh token for a fresh access token.

        Re-loads the user and refuses a disabled account or a **revoked** token (its
        ``token_version`` no longer matches the user's — ADR 0029). Raises
        :class:`promptforge_api.tokens.InvalidTokenError` for a bad/expired refresh token and
        :class:`InvalidCredentialsError` if the user no longer exists, is disabled, or the token
        has been revoked.
        """
        claims = decode_token(refresh_token, secret=self._jwt_secret, expected_type="refresh")
        user = self._repository.get_by_id(claims.subject)
        if user is None or not user.is_active or claims.token_version != user.token_version:
            raise InvalidCredentialsError
        return create_token(
            subject=user.id,
            role=user.role,
            token_type="access",
            secret=self._jwt_secret,
            ttl_seconds=self._access_ttl,
            token_version=user.token_version,
        )

    def create_user(
        self, email: str, password: str, role: str, *, actor: str = "system"
    ) -> User:
        """Create a user with a hashed password. Raises UserAlreadyExistsError on a clash."""
        normalised = _normalise_email(email)
        if self._repository.get_by_email(normalised) is not None:
            raise UserAlreadyExistsError(normalised)
        user = User(email=normalised, password_hash=hash_password(password), role=role)
        self._repository.add(user)
        self._repository.flush()
        if self._audits is not None:
            self._audits.record(
                actor=actor, action="user_created", target=f"user:{normalised} ({role})"
            )
        return user

    def get_user(self, user_id: uuid.UUID) -> User | None:
        """Load a user by id (used by the current-user dependency)."""
        return self._repository.get_by_id(user_id)

    def list_users(self) -> list[User]:
        """Return every user (admin-only at the boundary), newest first."""
        return self._repository.list_all()

    def update_user(
        self,
        user_id: uuid.UUID,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        actor: str = "system",
    ) -> User:
        """Change a user's role and/or active flag (admin-only at the boundary).

        Only the fields passed (non-``None``) are touched. Raises :class:`UserNotFoundError` for an
        unknown id and :class:`LastAdminError` if the change would leave no active admin. A role
        change or a deactivation **bumps** the user's ``token_version`` (ADR 0029) so outstanding
        tokens are revoked and the client must re-authenticate.
        """
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        role_changed = role is not None and role != user.role
        deactivating = is_active is False and user.is_active

        # Self-lockout guard: if this user is an active admin and the change takes them out of the
        # active-admin set (demote or deactivate), require at least one *other* active admin.
        leaving_admin_set = user.is_active and user.role == "admin" and (
            (role is not None and role != "admin") or deactivating
        )
        if leaving_admin_set and self._repository.count_active_admins(exclude=user_id) == 0:
            raise LastAdminError

        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        # Revoke outstanding tokens on a role change or deactivation (not on a pure reactivation:
        # there's nothing valid to invalidate, and a bump would needlessly log the user out again).
        if role_changed or deactivating:
            user.token_version += 1

        self._repository.flush()
        if self._audits is not None:
            self._audits.record(
                actor=actor, action="user_updated", target=_describe_update(user, role, is_active)
            )
        return user

    def revoke_tokens(self, user_id: uuid.UUID, *, actor: str = "system") -> User:
        """Invalidate all of a user's outstanding tokens by bumping ``token_version`` (ADR 0029).

        The "log this user out everywhere" action — a leaked-credential response that doesn't
        change the account's role or active state. Raises :class:`UserNotFoundError` for an
        unknown id.
        """
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        user.token_version += 1
        self._repository.flush()
        if self._audits is not None:
            self._audits.record(
                actor=actor, action="tokens_revoked", target=f"user:{user.email}"
            )
        return user


# Re-exported so callers can `except InvalidTokenError` from the service module if they prefer.
__all__ = [
    "AuthService",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "LastAdminError",
    "TokenPair",
    "UserAlreadyExistsError",
    "UserNotFoundError",
]
