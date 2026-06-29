"""structlog configuration for the worker: JSON logs to stdout.

Mirrors the API's logging setup so every component emits the same line shape. As in
the API, ``merge_contextvars`` pulls any bound contextvars (e.g. the ``request_id``
propagated from the submitting request) into every log line for that task, with no
manual threading. The correlation-id binding itself is wired in Sprint 6's stub-task
task via Celery signals.
"""

import logging
import sys

import structlog

from promptforge_worker.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog to emit JSON to stdout at the configured level."""
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
