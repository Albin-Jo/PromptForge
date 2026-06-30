"""Map domain exceptions to HTTP responses in one place.

Services raise plain domain exceptions and stay ignorant of HTTP (CLAUDE.md:
services hold logic, routers do HTTP only). Registering handlers on the app keeps
routers thin — they call the service and let these handlers translate failures —
and keeps the error→status mapping from being scattered and drifting per route.
The response body matches FastAPI's default ``{"detail": ...}`` shape.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from promptforge_api.composition.builder import BlockReferenceNotFoundError
from promptforge_api.composition.graph import CompositionCycleError
from promptforge_api.exceptions import (
    DatasetAlreadyExistsError,
    DatasetInUseError,
    DatasetNotFoundError,
    EmptyGoldenSetError,
    GoldenSetMissingError,
    PromptNotFoundError,
    TraceNotFoundError,
    VersionNotFoundError,
)
from promptforge_api.services.auth import UserAlreadyExistsError
from promptforge_api.services.blocks import (
    BlockAlreadyExistsError,
    BlockNotFoundError,
    BlockVersionNotFoundError,
)
from promptforge_api.services.prompts import (
    InvalidOutputSchemaError,
    LabelNotFoundError,
    PromptAlreadyExistsError,
    RenderVariableError,
)
from promptforge_api.templating import VariableContractError

_logger = structlog.get_logger(__name__)

# Domain exception → HTTP status. 404 for "no such thing", 409 for name clashes,
# 422 for requests that are well-formed but violate a registry rule (variable
# contract, bad output schema, wrong render variables, a circular reference, or a
# reference to a block version that doesn't exist). Blocks reuse the same
# contract-violation error (VariableContractError) as prompts (ADR 0004).
_STATUS_BY_EXCEPTION: dict[type[Exception], int] = {
    PromptNotFoundError: status.HTTP_404_NOT_FOUND,
    VersionNotFoundError: status.HTTP_404_NOT_FOUND,
    TraceNotFoundError: status.HTTP_404_NOT_FOUND,
    LabelNotFoundError: status.HTTP_404_NOT_FOUND,
    PromptAlreadyExistsError: status.HTTP_409_CONFLICT,
    VariableContractError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidOutputSchemaError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RenderVariableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    BlockNotFoundError: status.HTTP_404_NOT_FOUND,
    BlockVersionNotFoundError: status.HTTP_404_NOT_FOUND,
    BlockAlreadyExistsError: status.HTTP_409_CONFLICT,
    CompositionCycleError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    BlockReferenceNotFoundError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # Promotion gate (Sprint 11): 404 for a missing dataset, 409 for a name clash or a prompt
    # with no golden set to gate against, 422 for attaching an empty golden set.
    DatasetNotFoundError: status.HTTP_404_NOT_FOUND,
    DatasetAlreadyExistsError: status.HTTP_409_CONFLICT,
    GoldenSetMissingError: status.HTTP_409_CONFLICT,
    EmptyGoldenSetError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # Deleting a dataset a prompt still gates on is a conflict, not a not-found (ADR 0024).
    DatasetInUseError: status.HTTP_409_CONFLICT,
    # Human auth (Sprint 13): creating a user whose email is taken is a name clash.
    UserAlreadyExistsError: status.HTTP_409_CONFLICT,
}


def _make_handler(
    status_code: int,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


async def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the real error, return a generic body (no stack-trace leak).

    Anything not mapped above is a bug, not a client error. We log it with the bound
    ``request_id`` (so it's traceable) and return an opaque 500 — never the exception text, which
    could expose internals. Mapped domain exceptions and ``HTTPException`` are handled before this.
    """
    _logger.exception("unhandled_exception", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error"},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register a handler per domain exception so routers can stay HTTP-free."""
    for exception_type, status_code in _STATUS_BY_EXCEPTION.items():
        app.add_exception_handler(exception_type, _make_handler(status_code))
    # Catch-all for anything unmapped — keeps a bug from leaking internals to the client.
    app.add_exception_handler(Exception, _unhandled_exception_handler)
