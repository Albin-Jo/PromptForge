"""The LLM gateway: one internal interface in front of every model provider.

Everything outside this package talks to :class:`~promptforge_api.gateway.gateway.LLMGateway`
and never imports a vendor SDK (or ``litellm``) directly — swapping providers is a
config change, not a code change (ADR 0006, CLAUDE.md part 5).
"""

from promptforge_api.gateway.errors import (
    GatewayError,
    PermanentProviderError,
    RateLimitedError,
    TransientProviderError,
)
from promptforge_api.gateway.gateway import Completion, LLMGateway, StreamChunk, Usage
from promptforge_api.gateway.schemas import Message, ModelConfig

__all__ = [
    "Completion",
    "GatewayError",
    "LLMGateway",
    "Message",
    "ModelConfig",
    "PermanentProviderError",
    "RateLimitedError",
    "StreamChunk",
    "TransientProviderError",
    "Usage",
]
