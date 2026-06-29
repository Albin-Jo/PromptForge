"""Worker task exceptions.

Distinguishing *transient* failures (worth retrying) from *permanent* ones (retrying
will never help) is the whole basis of a sane retry policy. Tasks raise
:class:`TransientEvalError` for the former; everything else is treated as permanent and
fails fast rather than burning the retry budget on a doomed call.
"""


class TransientEvalError(Exception):
    """A temporary failure (e.g. a flaky dependency) that a retry may resolve."""


class TransientScanError(Exception):
    """A temporary failure during a security scan worth retrying.

    The injection scanner's LLM-judge pass calls the gateway; a retryable gateway failure
    (already exhausted internally) is re-raised as this so the task retries the whole scan under
    its longer backoff. A bad rule or a missing version is *permanent* and fails fast instead.
    """


class TransientWebhookError(Exception):
    """A webhook delivery failure worth retrying — a network error or a 5xx from the receiver.

    A 4xx (the receiver rejected the payload) is *permanent*: retrying the same body won't help,
    so it is logged and the task fails fast rather than hammering a misconfigured endpoint.
    """
