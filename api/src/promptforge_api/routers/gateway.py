"""HTTP layer for the LLM gateway: a thin streaming completion endpoint.

This route exists to *exercise* the gateway end-to-end (same code path, any provider,
live token streaming) — it deliberately does not touch the registry. Rendering a
stored version and then calling the model is the SDK's job in Phase 4; here the
caller supplies messages and model config directly.

The handler is ``async def``: a provider call is network I/O, and streaming needs an
async generator. No database is involved, so it never blocks the sync persistence
layer (ADR 0003 / ADR 0006).
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from promptforge_api.config import Settings, get_settings
from promptforge_api.gateway import GatewayError, LLMGateway, Message, ModelConfig

router = APIRouter(tags=["gateway"])
_logger = structlog.get_logger(__name__)


class CompletionRequest(BaseModel):
    """Body for a streaming completion: the messages and the model config."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Message]
    config: ModelConfig


class ModelsResponse(BaseModel):
    """The configured model identifiers the playground's model picker offers."""

    models: list[str]


def get_gateway() -> LLMGateway:
    """Provide a gateway wired to the real provider backend (overridden in tests)."""
    return LLMGateway()


GatewayDep = Annotated[LLMGateway, Depends(get_gateway)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/models")
async def list_models(settings: SettingsDep) -> ModelsResponse:
    """List the model identifiers configured for the playground's model picker.

    Read-only and non-secret, so there is no role gate (consistent with the other reads).
    Empty when ``gateway_models`` is unconfigured — the UI then falls back to a free-text
    model field so a bare local run still works.
    """
    return ModelsResponse(models=settings.gateway_models)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent Event frame: an ``event:`` name and a ``data:`` line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/complete")
async def complete(payload: CompletionRequest, gateway: GatewayDep) -> StreamingResponse:
    """Stream a completion token-by-token as Server-Sent Events.

    Each token delta is a ``token`` event; the stream ends with a ``done`` event. A
    provider failure becomes an ``error`` event rather than an HTTP status — once the
    stream opens we've already sent ``200 OK``, so the error has to ride the stream.
    """

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in gateway.stream(config=payload.config, messages=payload.messages):
                yield _sse_event(
                    "token", {"content": chunk.content, "finish_reason": chunk.finish_reason}
                )
            yield _sse_event("done", {})
        except GatewayError as exc:
            yield _sse_event("error", {"type": type(exc).__name__, "detail": str(exc)})
        except Exception:
            # Headers (200 OK) are already sent, so an unexpected failure has to ride
            # the stream as an error event rather than become an HTTP status — but we
            # don't leak its detail to the client. Log it so it isn't silently lost.
            _logger.exception("gateway_stream_unexpected_error", model=payload.config.model)
            yield _sse_event("error", {"type": "InternalError", "detail": "internal error"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
