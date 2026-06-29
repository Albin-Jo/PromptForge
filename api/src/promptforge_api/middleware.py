"""Correlation-id middleware: one id per request, on every log line.

The id is read from an inbound ``X-Request-ID`` header (so a caller's id is
preserved across hops) or minted fresh. It is bound to a contextvar for the
duration of the request and echoed back in the response header.
"""

import time
import uuid

import structlog
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from promptforge_api import ratelimit
from promptforge_api.config import get_settings
from promptforge_api.tokens import InvalidTokenError, decode_token

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign/propagate a correlation id and log one line per completed request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request_complete",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


# Conservative response headers applied to every response (Sprint 13 hardening). We deliberately
# omit a Content-Security-Policy: a strict one breaks the Swagger UI at /docs (inline scripts +
# CDN), and a JSON API gains little from a permissive one — CSP is parked in the learning backlog.
_SECURITY_HEADERS = {
    # Stop browsers from MIME-sniffing a response into a different content type.
    "X-Content-Type-Options": "nosniff",
    # This API renders no HTML meant to be framed; deny framing to blunt clickjacking.
    "X-Frame-Options": "DENY",
    # Don't leak the (possibly id-bearing) URL to third parties via the Referer header.
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a small, fixed set of defensive headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject a request whose declared body size exceeds the configured maximum (413).

    Checks ``Content-Length`` up front so an oversized payload is refused before it is read into
    memory. A request with no ``Content-Length`` (e.g. chunked) is passed through — bounding those
    would mean buffering the stream, which is out of scope for v0.1.
    """

    def __init__(self, app: object, *, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > self._max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "request body too large"},
                )
        return await call_next(request)


# Paths never rate-limited — liveness must answer even while a caller is being throttled.
_RATE_LIMIT_EXEMPT = frozenset({"/healthz"})


def _client_ip(request: Request, *, trust_forwarded: bool) -> str:
    """The caller's IP for rate-limit keying.

    Behind a trusted proxy the socket peer is the proxy, so all anonymous callers would share one
    bucket; when ``trust_forwarded`` is set we use the first hop in ``X-Forwarded-For`` instead.
    That header is caller-spoofable, so we only honor it when explicitly told the proxy sets it.
    """
    if trust_forwarded:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _principal_key(request: Request, *, jwt_secret: str | None, trust_forwarded: bool) -> str:
    """Identify the caller for rate limiting: API key, else user, else client IP.

    Keying by credential (not just IP) means a shared NAT doesn't throttle everyone together, and a
    leaked/abused key is the unit that gets limited. The bearer token is decoded best-effort — an
    invalid one just falls through to the IP, since an invalid token is rejected downstream anyway.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api-key:{api_key[:8]}"

    authorization = request.headers.get("Authorization")
    if jwt_secret and authorization and authorization.lower().startswith("bearer "):
        try:
            claims = decode_token(authorization[7:], secret=jwt_secret, expected_type="access")
            return f"user:{claims.subject}"
        except InvalidTokenError:
            pass

    return f"ip:{_client_ip(request, trust_forwarded=trust_forwarded)}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Throttle requests per principal via the configured limiter (429 when exceeded)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)

        settings = get_settings()
        key = _principal_key(
            request,
            jwt_secret=settings.jwt_secret,
            trust_forwarded=settings.rate_limit_trust_forwarded,
        )
        decision = ratelimit.get_rate_limiter().hit(key)
        if not decision.allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return await call_next(request)
