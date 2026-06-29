"""Errors raised by the eval engine.

A scorer can fail in two distinct ways, and callers care about the difference:

- the *grading machinery* failed — the LLM judge's provider call errored, or it
  returned something we couldn't parse into a verdict; or
- (later) the *inputs* were invalid for that scorer.

Everything roots at :class:`ScorerError` so a caller can catch the whole family
without knowing which scorer ran. Provider failures from the gateway keep their own
:class:`~promptforge_api.gateway.errors.GatewayError` type and are *not* swallowed
here — a flaky provider is the gateway's story to tell.
"""


class ScorerError(Exception):
    """Base for any failure originating inside a scorer."""


class JudgeParseError(ScorerError):
    """The LLM judge replied, but not in a shape we could read as a verdict.

    Carries the raw model text so the failure is debuggable — a judge that drifts
    off the JSON contract is a prompt problem we want to *see*, not silently pass.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
