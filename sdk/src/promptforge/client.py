"""The PromptForge client — what an app imports to fetch a rendered prompt.

The public surface is one method, :meth:`PromptForgeClient.get_prompt`, which makes a
single call to the server's render-by-label endpoint and returns a
:class:`~promptforge.models.RenderedPrompt`. This is a *floating* fetch (see the
pinned-vs-floating ADR): you ask for a label ('production') and always get whatever
version it currently points at, so a deploy is picked up without changing your code.

This slice is the happy path only. The network round-trip lives in :meth:`_fetch`, kept
as its own seam so the later slices can wrap it: a cache in front of it, and a
last-known-good / baked-in-default fallback around it — without touching ``get_prompt``.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

import httpx

from promptforge.cache import CacheKey, CacheStats, PromptCache, make_key
from promptforge.errors import (
    PromptForgeAPIError,
    PromptForgeConnectionError,
    PromptNotFoundError,
)
from promptforge.models import RenderedPrompt

# Stdlib logging (no extra dep): a caller wires this into their own handlers. We log a
# warning whenever we serve a fallback so "why did I get an old prompt?" is answerable.
_logger = logging.getLogger("promptforge")

# What a caller may pass as a baked-in default: ready-rendered text (convenience) or a
# full RenderedPrompt carrying model settings too.
type Default = str | RenderedPrompt

_DEFAULT_LABEL = "production"
# A client fetch should fail fast: the whole point is to fall back quickly when the
# platform is slow or down, not to hang the caller's request. Tunable per client.
_DEFAULT_TIMEOUT = 5.0
# How long a fetched prompt stays fresh. For a floating fetch this *is* the staleness
# window after a deploy: a re-pointed label is picked up within one TTL. 60s trades a
# minute of post-deploy lag for far fewer network round-trips.
_DEFAULT_CACHE_TTL = 60.0


class PromptForgeClient:
    """Fetches rendered prompts from a PromptForge server.

    Construct once and reuse — it holds a pooled HTTP connection. Use it as a context
    manager (``with PromptForgeClient(...) as c:``) or call :meth:`close` when done.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Wire the client to a server.

        ``api_key`` is sent as the ``X-API-Key`` header on every request (the server
        enforces it in a later slice; sending it now is harmless if unset). ``timeout``
        bounds each call so a hung platform degrades fast. ``cache_ttl`` is how long a
        fetched prompt is served from the in-process cache before re-fetching (set to 0
        to always hit the server). ``transport`` lets callers (and tests) supply a custom
        httpx transport — a ``MockTransport`` for failure injection, or an
        ``ASGITransport`` to drive the API in-process.
        """
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=headers,
            transport=transport,
        )
        self._cache = PromptCache(ttl=cache_ttl)
        self._stats = CacheStats()

    @property
    def cache_stats(self) -> CacheStats:
        """Live hit/miss counters for this client's cache (the observability hook)."""
        return self._stats

    def get_prompt(
        self,
        name: str,
        *,
        label: str = _DEFAULT_LABEL,
        variables: dict[str, str] | None = None,
        default: Default | None = None,
    ) -> RenderedPrompt:
        """Fetch and render the version *label* points at, filled with *variables*.

        Resolution order — each step falls through to the next only on failure:

        1. a fresh (within-TTL) cached result, returned without touching the network;
        2. a fresh fetch from the API, which is then cached;
        3. on a *connection* failure (platform unreachable) — the last-known-good value,
           i.e. an expired cache entry for this exact request;
        4. on a connection failure with no usable cache — the baked-in *default*;
        5. otherwise the :class:`PromptForgeConnectionError` is re-raised.

        Only an unreachable platform triggers the fallback. A real API error (wrong
        variables, a missing prompt, a 5xx) propagates — masking those behind a stale
        value would hide bugs, not survive an outage.
        """
        variables = variables or {}
        key = make_key(name, label, variables)

        cached = self._cache.get_fresh(key)
        if cached is not None:
            self._stats.record_hit()
            return cached

        self._stats.record_miss()
        try:
            result = self._fetch(name, label, variables)
        except PromptForgeConnectionError:
            return self._fallback(name, label, key, default)

        self._cache.set(key, result)
        return result

    def record_trace(
        self,
        rendered: RenderedPrompt,
        *,
        model: str | None = None,
        status: str = "ok",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        provider: str | None = None,
        provider_model: str | None = None,
        input: str | None = None,
        output: str | None = None,
        error_type: str | None = None,
        trace_id: str | None = None,
    ) -> str | None:
        """Report the model call this *rendered* prompt drove, for observability.

        Call it after your own model call. The version identity travels on *rendered*, so the
        resulting trace is attributed to the exact version — that's what makes "cost/latency/
        quality per version" possible. ``model`` defaults to the version's configured model;
        pass it explicitly if you called a different one. ``status`` is ``"ok"`` or ``"error"``.

        **Fire-and-forget and never raises.** Tracing is telemetry: a tracing failure (platform
        down, bad response, malformed reply) must not break the caller's request, so any error is
        logged and swallowed, returning ``None``. On success it returns the server's ``trace_id``.
        The happy path is a single POST the server answers ``202`` to after merely *enqueuing* the
        write, so it's cheap — but it is still a synchronous call on your thread: a slow or hung
        platform can block up to this client's ``timeout`` before the swallow kicks in. Give the
        client a short timeout if that matters; a fully-backgrounded emit is a later refinement.
        """
        if status not in ("ok", "error"):
            # Fail locally and visibly rather than round-trip to a guaranteed 422 that we'd then
            # silently swallow — a typo'd status would otherwise drop the trace with no clear cause.
            _logger.warning("promptforge: record_trace skipped — invalid status %r", status)
            return None

        call_model = model or (rendered.model_settings or {}).get("model")
        if not call_model:
            _logger.warning(
                "promptforge: record_trace skipped — no model given and none on version"
            )
            return None

        body: dict[str, Any] = {
            "model": call_model,
            "status": status,
            "source": "sdk",
            "prompt_id": rendered.prompt_id,
            "prompt_version_id": rendered.prompt_version_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "provider": provider,
            "provider_model": provider_model,
            "input": input,
            "output": output,
            "error_type": error_type,
        }
        if trace_id is not None:
            body["id"] = trace_id
        # Drop unset fields so the server's extra="forbid"/validation sees only real values.
        body = {key: value for key, value in body.items() if value is not None}

        try:
            response = self._http.post("/traces", json=body)
            response.raise_for_status()
            # .json() is inside the try on purpose: a non-JSON body raises ValueError, which is
            # not an httpx.HTTPError — leaving it outside would let that escape into the caller
            # and break the "never raises" guarantee this method exists to provide.
            returned: Any = response.json().get("trace_id")
        except (httpx.HTTPError, ValueError) as exc:
            _logger.warning("promptforge: failed to record trace (ignored): %s", exc)
            return None
        return returned if isinstance(returned, str) else None

    def _fallback(
        self, name: str, label: str, key: CacheKey, default: Default | None
    ) -> RenderedPrompt:
        """Serve last-known-good, then the baked-in default, when the platform is down."""
        stale = self._cache.get_any(key)
        if stale is not None:
            self._stats.record_stale_served()
            _logger.warning(
                "promptforge: serving last-known-good for '%s' (label=%s) — API unreachable",
                name,
                label,
            )
            return stale

        if default is not None:
            self._stats.record_default_served()
            _logger.warning(
                "promptforge: serving baked-in default for '%s' (label=%s) — API unreachable",
                name,
                label,
            )
            if isinstance(default, RenderedPrompt):
                return default
            return RenderedPrompt(prompt=default, model_settings=None, output_schema=None)

        # Nothing to fall back to: the caller asked for resilience but gave us no cache
        # and no default. Re-raise so the failure is visible rather than silent.
        raise PromptForgeConnectionError(
            f"PromptForge unreachable and no cached value or default for '{name}' (label={label})"
        )

    def _fetch(self, name: str, label: str, variables: dict[str, str]) -> RenderedPrompt:
        """One network round-trip to the render-by-label endpoint.

        The seam the cache and fallback wrap. Translates transport and HTTP failures
        into the SDK's own exception types so callers never see httpx.
        """
        try:
            response = self._http.post(
                f"/prompts/{name}/render",
                json={"label": label, "variables": variables},
            )
        except httpx.RequestError as exc:
            # Connection refused, DNS failure, timeout — the platform is unreachable.
            raise PromptForgeConnectionError(f"could not reach PromptForge: {exc}") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise PromptNotFoundError(name, label)
        if response.is_error:
            raise PromptForgeAPIError(response.status_code, _detail(response))

        return RenderedPrompt.from_response(response.json())

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> PromptForgeClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _detail(response: httpx.Response) -> str | None:
    """Pull the server's ``{"detail": ...}`` message off an error response, if any."""
    try:
        body: Any = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None
