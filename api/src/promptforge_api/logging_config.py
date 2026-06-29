"""structlog configuration: JSON logs that carry the per-request correlation id.

``merge_contextvars`` is what pulls the ``request_id`` bound by the middleware
into every log line for that request, with no manual threading.
"""

import logging
import sys

import structlog

from promptforge_api.config import Settings


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
