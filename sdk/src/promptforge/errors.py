"""SDK exception hierarchy.

Callers catch *these* types, never httpx's. Every failure the client can raise is a
:class:`PromptForgeError`, so an app can wrap a whole ``get_prompt`` call in one
``except PromptForgeError`` and still distinguish the cases it cares about.

The split that matters for resilience: :class:`PromptForgeConnectionError` means
"the platform was unreachable" — that's the signal the fallback chain (later slice)
acts on. A :class:`PromptForgeAPIError` means the platform answered with an error
(a real 4xx/5xx); falling back to a stale value on, say, a 422 would hide a bug, so
those are kept distinct.
"""

from __future__ import annotations


class PromptForgeError(Exception):
    """Base class for every error the SDK raises."""


class PromptNotFoundError(PromptForgeError):
    """The prompt or its label does not exist on the server (HTTP 404)."""

    def __init__(self, name: str, label: str) -> None:
        super().__init__(f"no prompt '{name}' with label '{label}'")
        self.name = name
        self.label = label


class PromptForgeAPIError(PromptForgeError):
    """The server answered with a non-success status other than 404.

    ``status_code`` is the HTTP status; ``detail`` is the server's error message when
    it sent one. The platform *responded*, so this is a real error to surface — not a
    reachability problem to paper over with a cached value.
    """

    def __init__(self, status_code: int, detail: str | None = None) -> None:
        message = f"PromptForge API returned {status_code}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class PromptForgeConnectionError(PromptForgeError):
    """The server could not be reached (network error or timeout).

    This is the "pull the plug" case: the fallback chain treats it as the trigger to
    serve a last-known-good or baked-in default instead of propagating the failure.
    """
