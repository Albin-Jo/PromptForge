"""JWT minting and verification for the human-auth path (Sprint 13 / Phase 11, ADR 0018).

Pure functions over claims — no DB, no FastAPI, no settings: the caller passes the secret and
TTL, so this stays trivially unit-testable and reusable from both the login service and the
``get_current_user`` dependency. Tokens are HS256-signed JWTs carrying ``sub`` (user id), ``role``,
a ``type`` (access | refresh), and standard ``iat``/``exp`` claims.

Two safety choices worth knowing:

* **Algorithm is pinned on decode** (``algorithms=["HS256"]``) so a forged token can't downgrade
  to ``none`` or trick us into verifying with the wrong scheme — the classic JWT confusion bug.
* **The token ``type`` is checked**, so a refresh token can never be presented where an access
  token is required (or vice-versa).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

_ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    """Raised when a token is missing, malformed, expired, mis-signed, or the wrong type."""


@dataclass(frozen=True)
class TokenClaims:
    """The validated claims we care about, lifted out of the raw JWT payload."""

    subject: uuid.UUID
    role: str
    token_type: TokenType
    # The user's token_version at mint time (ADR 0029). A verify compares this against the user's
    # current column; a mismatch means the token was revoked. Absent on tokens minted before the
    # claim existed — read as 0 (see decode_token) so they still match a version-0 user.
    token_version: int = 0


def create_token(
    *,
    subject: uuid.UUID,
    role: str,
    token_type: TokenType,
    secret: str,
    ttl_seconds: int,
    token_version: int = 0,
    now: datetime | None = None,
) -> str:
    """Mint a signed JWT for *subject* with *role*, expiring *ttl_seconds* from now.

    *token_version* stamps the user's revocation counter into the token (ADR 0029). *now* is
    injectable so tests can mint an already-expired token without sleeping.
    """
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "ver": token_version,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(token: str, *, secret: str, expected_type: TokenType) -> TokenClaims:
    """Verify *token*'s signature, expiry, and ``type``; return its claims.

    Raises :class:`InvalidTokenError` for any failure — a bad signature, an expired token, a
    token of the wrong ``type``, or a payload missing/mangling the claims we require.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token")

    raw_subject = payload.get("sub")
    role = payload.get("role")
    if not isinstance(raw_subject, str) or not isinstance(role, str):
        raise InvalidTokenError("token is missing required claims")
    try:
        subject = uuid.UUID(raw_subject)
    except ValueError as exc:
        raise InvalidTokenError("token subject is not a valid id") from exc

    # A pre-ADR-0029 token has no "ver" claim; treat it as version 0 so it still matches a
    # version-0 user. A present-but-non-int claim is a malformed token — reject it.
    raw_version = payload.get("ver", 0)
    if not isinstance(raw_version, int) or isinstance(raw_version, bool):
        raise InvalidTokenError("token version claim is not an integer")

    return TokenClaims(
        subject=subject, role=role, token_type=expected_type, token_version=raw_version
    )
