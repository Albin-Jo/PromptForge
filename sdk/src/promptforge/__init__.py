"""PromptForge Python client SDK (caching + last-known-good fallback).

Import :class:`PromptForgeClient`, call :meth:`~client.PromptForgeClient.get_prompt`,
get back a :class:`RenderedPrompt`. Every error the SDK raises is a
:class:`PromptForgeError`.
"""

from promptforge.cache import CacheStats
from promptforge.client import PromptForgeClient
from promptforge.errors import (
    PromptForgeAPIError,
    PromptForgeConnectionError,
    PromptForgeError,
    PromptNotFoundError,
)
from promptforge.models import RenderedPrompt

__version__ = "0.1.0"

__all__ = [
    "PromptForgeClient",
    "PromptForgeError",
    "PromptForgeConnectionError",
    "PromptForgeAPIError",
    "PromptNotFoundError",
    "RenderedPrompt",
    "CacheStats",
    "__version__",
]
