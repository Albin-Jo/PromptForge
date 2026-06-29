"""API-key authentication for SDK clients.

A deliberately minimal gate: a request to a protected endpoint must carry an ``X-API-Key``
header matching one of the configured keys. This is *not* the user/role auth system (that
arrives in Sprint 13) — it's a static shared-secret check so the SDK fetch path isn't wide
open.

Two behaviours worth knowing:

* **Open when unconfigured.** With no ``api_keys`` set, the check is a no-op (like Redis
  being optional) — frictionless local/dev. Configure keys in production.
* **Constant-time comparison.** Keys are compared with :func:`secrets.compare_digest` so a
  caller can't probe a valid key by measuring response times.
"""

from __future__ import annotations

import secrets
from typing import Annotated

import bcrypt
from fastapi import Header, HTTPException, status

from promptforge_api.config import get_settings

# We call bcrypt directly rather than through passlib: passlib is unmaintained (2020) and its
# bcrypt backend breaks on bcrypt 5.x (ADR 0018). bcrypt salts each hash and `checkpw` is a
# constant-time compare. bcrypt only considers the first 72 bytes of a password and bcrypt 5
# *raises* on longer input instead of truncating, so we truncate explicitly — identically on
# hash and verify, so a >72-byte password keeps verifying.
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash of *password*, safe to store."""
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True iff *password* matches the stored *password_hash*.

    A malformed stored hash (e.g. not a bcrypt digest) makes ``checkpw`` raise ``ValueError``;
    we treat that as a non-match rather than letting it surface as a 500.
    """
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Reject the request unless it carries a valid ``X-API-Key`` (when keys are set).

    A FastAPI dependency: attach it via ``dependencies=[Depends(require_api_key)]``. Returns
    ``None`` on success; raises **401** when a key is required but missing or wrong.
    """
    keys = get_settings().api_keys
    if not keys:
        return  # auth disabled — no keys configured

    if x_api_key is None or not any(secrets.compare_digest(x_api_key, key) for key in keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )


def promotion_actor(
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    """Best-effort "who" for the promotion audit trail (Sprint 11).

    Records *which key* triggered a promotion without leaking it: a short prefix, never the
    whole key. This is **not** authentication — promotion isn't key-gated in v0.1 (real user
    identity + authz arrive in Sprint 13); it only attributes the action. No key → ``system``.
    """
    if x_api_key:
        return f"api-key:{x_api_key[:8]}"
    return "system"
