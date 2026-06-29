"""Worker configuration, loaded from the environment (12-factor).

The worker keeps its **own** settings object rather than importing the API's, so
``promptforge-worker`` never depends on ``promptforge-api`` (and vice versa). Both
read the same ``PROMPTFORGE_``-prefixed environment, so a single ``.env`` / compose
block configures the whole stack.

Broker and result backend are deliberately **separate Redis logical DBs** (``/1``
and ``/2``) from the API's hot-prompt cache (``/0``): one component flushing its DB
can never clobber another's keys, and a queued job can't collide with a cached render.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from promptforge_worker import __version__


class Settings(BaseSettings):
    """Process-wide worker configuration, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="PROMPTFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "promptforge-worker"
    version: str = __version__
    log_level: str = "INFO"

    # Number of concurrent task slots. Our work is I/O-bound (LLM calls, scans), so the
    # worker runs a *threads* pool (see celery_app.py) where this is the thread count —
    # how many tasks can wait on I/O at once in one process. Tune against provider latency
    # and connection limits once observability (Phase 7) gives real numbers.
    worker_concurrency: int = 8

    # Redis transport that carries task messages from producer (API) to worker.
    # DB index 1 — distinct from the API cache (0) and the result backend (2). The
    # compose stack injects these by service name; the localhost defaults let a worker
    # run outside the container reach the same Redis.
    celery_broker_url: str = "redis://localhost:6379/1"
    # Where task return values + states are stored so a caller can poll the job id.
    celery_result_backend: str = "redis://localhost:6379/2"

    # Note on the database: the eval task talks to Postgres, but the worker reuses the API's
    # engine (promptforge_api.db.engine, per ADR 0011) rather than holding its own DSN here.
    # That engine reads PROMPTFORGE_DATABASE_URL from the same environment, so the worker
    # process just needs that env var set (compose injects it); there's no worker-owned setting.


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    return Settings()
