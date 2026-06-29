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


@dataclass(frozen=True)
class TokenPair:
    """The result of a successful login: a short access token + a long refresh token."""

    access_token: str
    refresh_token: str


def _normalise_email(email: str) -> str:
    """Lower-case and trim so uniqueness and lookups are case-insensitive."""
    return email.strip().lower()


class AuthService:
    """Use-cases for human auth: login, refresh, create user, load current user."""

    def __init__(
        self,
        repository: UserRepository,
        *,
        jwt_secret: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._jwt_secret = jwt_secret
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

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
        )
        refresh = create_token(
            subject=user.id,
            role=user.role,
            token_type="refresh",
            secret=self._jwt_secret,
            ttl_seconds=self._refresh_ttl,
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    def login(self, email: str, password: str) -> TokenPair:
        """Authenticate and issue a token pair in one step."""
        return self.issue_tokens(self.authenticate(email, password))

    def refresh(self, refresh_token: str) -> str:
        """Exchange a valid refresh token for a fresh access token.

        Re-loads the user and refuses a disabled account. Raises
        :class:`promptforge_api.tokens.InvalidTokenError` for a bad/expired refresh token and
        :class:`InvalidCredentialsError` if the user no longer exists or is disabled.
        """
        claims = decode_token(refresh_token, secret=self._jwt_secret, expected_type="refresh")
        user = self._repository.get_by_id(claims.subject)
        if user is None or not user.is_active:
            raise InvalidCredentialsError
        return create_token(
            subject=user.id,
            role=user.role,
            token_type="access",
            secret=self._jwt_secret,
            ttl_seconds=self._access_ttl,
        )

    def create_user(self, email: str, password: str, role: str) -> User:
        """Create a user with a hashed password. Raises UserAlreadyExistsError on a clash."""
        normalised = _normalise_email(email)
        if self._repository.get_by_email(normalised) is not None:
            raise UserAlreadyExistsError(normalised)
        user = User(email=normalised, password_hash=hash_password(password), role=role)
        self._repository.add(user)
        self._repository.flush()
        return user

    def get_user(self, user_id: uuid.UUID) -> User | None:
        """Load a user by id (used by the current-user dependency)."""
        return self._repository.get_by_id(user_id)

    def list_users(self) -> list[User]:
        """Return every user (admin-only at the boundary), newest first."""
        return self._repository.list_all()


# Re-exported so callers can `except InvalidTokenError` from the service module if they prefer.
__all__ = [
    "AuthService",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "TokenPair",
    "UserAlreadyExistsError",
]
