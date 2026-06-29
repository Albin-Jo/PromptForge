"""The provider-agnostic LLM gateway.

:class:`LLMGateway` is the single seam between PromptForge and every model vendor.
It wraps LiteLLM's unified ``acompletion`` interface (ADR 0006) and translates the
OpenAI-shaped response LiteLLM returns into our own :class:`Completion` dataclass —
so callers depend on *our* types, not LiteLLM's, and a future change of provider
library wouldn't ripple past this file.

The gateway is **async**: a completion is slow network I/O, the textbook case for
``await``. This is the system's first async surface; the registry/DB stack stays
synchronous (ADR 0003) and the two coexist — async routes for provider calls, sync
routes (run in a threadpool) for database work.

Every call is wrapped in a resilient path: a per-call timeout bounds how long we
wait, provider failures are classified into the gateway taxonomy (see
:mod:`~promptforge_api.gateway.errors`), and retryable ones are retried with
exponential backoff + jitter. Permanent failures fail fast.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from promptforge_api.gateway.errors import (
    RETRYABLE_ERRORS,
    GatewayError,
    classify_provider_error,
)
from promptforge_api.gateway.schemas import Message, ModelConfig

# A provider call is the slowest, flakiest operation in the system, so it gets its
# own log trail. ``merge_contextvars`` (logging_config) threads the request's
# correlation id into every line here without us passing it down.
_logger = structlog.get_logger(__name__)

# The injected provider call. Real default is ``litellm.acompletion``; tests pass a
# fake so the suite never needs a network, a key, or even litellm installed. Typed
# loosely because LiteLLM's response type stays behind this boundary.
CompletionFn = Callable[..., Awaitable[Any]]

# Distinguishes "the stream had no chunks at all" from a real first chunk, since the
# first chunk could legitimately be falsy. Used as the default for ``anext``.
_STREAM_EXHAUSTED: Any = object()


@dataclass(frozen=True)
class Usage:
    """Token accounting for one completion, as reported by the provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class Completion:
    """A finished, non-streamed completion in PromptForge's own vocabulary."""

    content: str
    # The model the provider actually served (may be more specific than requested).
    model: str
    finish_reason: str | None
    usage: Usage | None


@dataclass(frozen=True)
class StreamChunk:
    """One incremental piece of a streamed completion.

    ``content`` is the text delta for this chunk (``""`` on the final chunk, which
    typically only carries a ``finish_reason``). Our own type so callers never touch
    LiteLLM's chunk objects.
    """

    content: str
    finish_reason: str | None


class LLMGateway:
    """Calls any provider through one interface; provider chosen by ``ModelConfig``."""

    def __init__(
        self,
        completion_fn: CompletionFn | None = None,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 30.0,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
    ) -> None:
        """Wire the gateway to a completion backend and its resilience policy.

        ``completion_fn`` defaults to ``litellm.acompletion``, imported lazily so
        importing this module stays cheap and litellm is only required when a real
        call is made. The retry/timeout knobs default to sensible production values
        (ADR 0006); the composition root may override them from settings, and tests
        set ``backoff_base=0`` to retry without real sleeps.
        """
        if completion_fn is None:
            import litellm

            completion_fn = litellm.acompletion
        self._acompletion = completion_fn
        self._max_attempts = max_attempts
        self._timeout_seconds = timeout_seconds
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def complete(self, *, config: ModelConfig, messages: list[Message]) -> Completion:
        """Run one chat completion, with timeout + bounded retry, and parse the result.

        The same code path reaches any vendor: ``config.model`` selects the provider,
        ``to_litellm_kwargs`` forwards only the sampling knobs that were set. Transient
        failures and rate limits are retried with exponential backoff + jitter; a
        permanent failure (or exhausting the attempts) propagates as a ``GatewayError``.
        """
        _logger.info("gateway_call_started", model=config.model, streaming=False)

        def _log_retry(retry_state: RetryCallState) -> None:
            exc = retry_state.outcome.exception() if retry_state.outcome else None
            _logger.warning(
                "gateway_call_retrying",
                model=config.model,
                attempt=retry_state.attempt_number,
                error_type=type(exc).__name__ if exc else None,
                sleep_seconds=getattr(retry_state.next_action, "sleep", None),
            )

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(RETRYABLE_ERRORS),
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_random_exponential(multiplier=self._backoff_base, max=self._backoff_max),
                reraise=True,  # surface the real GatewayError, not tenacity's RetryError
                before_sleep=_log_retry,
            ):
                with attempt:
                    completion = await self._complete_once(config, messages)
                    _logger.info(
                        "gateway_call_succeeded",
                        model=config.model,
                        finish_reason=completion.finish_reason,
                        total_tokens=completion.usage.total_tokens if completion.usage else None,
                    )
                    return completion
        except GatewayError as exc:
            _logger.warning(
                "gateway_call_failed", model=config.model, error_type=type(exc).__name__
            )
            raise
        raise AssertionError("unreachable: AsyncRetrying always returns or raises")

    async def stream(
        self, *, config: ModelConfig, messages: list[Message]
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion as incremental :class:`StreamChunk`s.

        The timeout bounds *time-to-first-token* — opening the stream **and** pulling
        the first chunk — because litellm performs the network round-trip lazily on
        the first ``__anext__``, not on the ``await``. Once tokens are flowing we stop
        timing (a long generation legitimately takes a while) and we don't retry,
        since we've already emitted bytes and can't un-send them (ADR 0006). A failure
        — opening, first-token, or mid-stream — surfaces as a classified
        ``GatewayError`` for the caller to turn into an error event.
        """
        _logger.info("gateway_call_started", model=config.model, streaming=True)
        try:
            async for parsed in self._stream_chunks(config, messages):
                yield parsed
        except GatewayError as exc:
            _logger.warning(
                "gateway_call_failed",
                model=config.model,
                error_type=type(exc).__name__,
                streaming=True,
            )
            raise
        _logger.info("gateway_stream_completed", model=config.model)

    async def _stream_chunks(
        self, config: ModelConfig, messages: list[Message]
    ) -> AsyncIterator[StreamChunk]:
        """The streaming mechanics: bounded open + first token, then untimed flow.

        Kept separate from :meth:`stream` so the logging wrapper there stays readable.
        """
        try:
            async with asyncio.timeout(self._timeout_seconds):
                provider_stream = await self._acompletion(
                    messages=[message.model_dump() for message in messages],
                    stream=True,
                    **config.to_litellm_kwargs(),
                )
                iterator = aiter(provider_stream)
                first = await anext(iterator, _STREAM_EXHAUSTED)
        except GatewayError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from exc

        if first is _STREAM_EXHAUSTED:
            return  # empty stream — nothing to yield

        # The first chunk was fetched under the deadline above; remaining chunks flow
        # untimed. Wrap both in the same failure-classification.
        try:
            parsed = _parse_chunk(first)
            if parsed is not None:
                yield parsed
            async for chunk in iterator:
                parsed = _parse_chunk(chunk)
                if parsed is not None:
                    yield parsed
        except GatewayError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from exc

    async def _complete_once(self, config: ModelConfig, messages: list[Message]) -> Completion:
        """One bounded attempt: enforce the deadline and normalise any failure."""
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._acompletion(
                    messages=[message.model_dump() for message in messages],
                    **config.to_litellm_kwargs(),
                )
        except GatewayError:
            raise  # already classified; don't re-wrap
        except Exception as exc:
            raise classify_provider_error(exc) from exc
        return _parse_completion(response)


def _parse_completion(response: Any) -> Completion:
    """Translate LiteLLM's OpenAI-shaped response into our :class:`Completion`."""
    choice = response.choices[0]
    # A provider may legitimately return no text (e.g. a pure tool call); normalise
    # to an empty string so ``content`` is always a ``str``.
    content = choice.message.content or ""
    return Completion(
        content=content,
        model=response.model,
        finish_reason=choice.finish_reason,
        usage=_parse_usage(response.usage),
    )


def _parse_chunk(chunk: Any) -> StreamChunk | None:
    """Translate one LiteLLM stream chunk into a :class:`StreamChunk`.

    Returns ``None`` for empty/keepalive chunks (no delta text and no finish
    reason) so the caller only ever sees meaningful events.
    """
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    choice = choices[0]
    delta = getattr(choice, "delta", None)
    content = getattr(delta, "content", None) if delta is not None else None
    finish_reason = choice.finish_reason
    if content is None and finish_reason is None:
        return None
    return StreamChunk(content=content or "", finish_reason=finish_reason)


def _parse_usage(usage: Any) -> Usage | None:
    """Pull token counts off the response's usage object, if the provider sent one."""
    if usage is None:
        return None
    return Usage(
        prompt_tokens=usage.prompt_tokens or 0,
        completion_tokens=usage.completion_tokens or 0,
        total_tokens=usage.total_tokens or 0,
    )
