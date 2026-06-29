"""The gateway's error taxonomy and the LiteLLM-to-taxonomy classifier.

Callers should be able to answer one question without knowing anything about the
provider: *should I bother trying again?* So every provider failure is collapsed
into three of our own exceptions:

- :class:`TransientProviderError` — a blip (timeout, dropped connection, provider
  5xx). Retrying may well succeed.
- :class:`RateLimitedError` — also retryable, but kept distinct so logs/metrics and
  (later) backpressure can treat throttling specially.
- :class:`PermanentProviderError` — retrying is pointless (bad key, malformed
  request, unknown model, context-window overflow). Fail fast.

LiteLLM already normalises every vendor onto an OpenAI-shaped hierarchy rooted at
``litellm.APIError`` (verified: ``RateLimitError``/``InternalServerError`` are
``APIStatusError`` subclasses; ``ContextWindowExceededError`` extends
``BadRequestError``). :func:`classify_provider_error` maps that hierarchy onto ours
and is the *only* place that knows those LiteLLM types.
"""


class GatewayError(Exception):
    """Base for every error the gateway raises. Carries the underlying cause."""

    def __init__(self, message: str, *, original: Exception | None = None) -> None:
        super().__init__(message)
        # The provider exception we wrapped, kept for logging/debugging without
        # leaking LiteLLM types into the caller's normal control flow.
        self.original = original


class TransientProviderError(GatewayError):
    """A retryable provider failure: timeout, connection drop, or provider 5xx."""


class RateLimitedError(GatewayError):
    """The provider throttled us (HTTP 429). Retryable, but tracked separately."""


class PermanentProviderError(GatewayError):
    """A non-retryable provider failure: auth, bad request, unknown model, etc."""


# Both are safe to retry; permanent errors are deliberately excluded. The resilient
# call path keys its retry predicate off this tuple.
RETRYABLE_ERRORS: tuple[type[GatewayError], ...] = (TransientProviderError, RateLimitedError)


def classify_provider_error(exc: Exception) -> GatewayError:
    """Map a raised exception onto the gateway taxonomy.

    Ordering matters: the specific 429 and the permanent 4xx classes are checked
    before the broad transient/connection classes, because LiteLLM's ``RateLimitError``
    and friends all ultimately subclass ``APIError``. A non-provider exception (a
    programming bug, say) is re-raised untouched rather than masquerading as a
    provider failure. ``litellm`` is imported lazily so this module stays importable
    without it (and so nothing else needs it).
    """
    import litellm

    if isinstance(exc, litellm.RateLimitError):
        return RateLimitedError(str(exc), original=exc)
    if isinstance(
        exc,
        (
            litellm.AuthenticationError,
            litellm.PermissionDeniedError,
            litellm.BadRequestError,  # also covers ContextWindowExceededError
            litellm.NotFoundError,
            litellm.UnprocessableEntityError,
        ),
    ):
        return PermanentProviderError(str(exc), original=exc)
    if isinstance(
        exc,
        (
            litellm.Timeout,
            litellm.APIConnectionError,
            litellm.InternalServerError,
            litellm.ServiceUnavailableError,
        ),
    ):
        return TransientProviderError(str(exc), original=exc)
    # Our own per-call deadline firing (asyncio.timeout raises TimeoutError) — treat
    # a slow provider as transient and let the retry policy decide.
    if isinstance(exc, TimeoutError):
        return TransientProviderError("provider call timed out", original=exc)
    # An unknown provider error: trust the HTTP status if LiteLLM attached one —
    # 5xx is transient, anything else fails fast.
    if isinstance(exc, litellm.APIError):
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and status >= 500:
            return TransientProviderError(str(exc), original=exc)
        return PermanentProviderError(str(exc), original=exc)
    # Not a provider error at all — don't disguise it as one.
    raise exc
