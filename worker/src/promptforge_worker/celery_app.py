"""The Celery application: the worker's entry point and configuration root.

Run it with::

    celery -A promptforge_worker.celery_app worker --loglevel=INFO

The pool is configured to **threads** (see ``worker_pool`` below), which needs no
``os.fork()``, so this same command works on Windows (local) and Linux (compose) —
no ``--pool=solo`` workaround. The concurrency model is recorded in the Sprint 6 ADR.

**Broker vs result backend.** The *broker* (Redis DB 1) is the transport that carries
task messages from the producer (the API) to the worker. The *result backend* (Redis
DB 2) is where a task's return value and state are stored so a caller can later look
them up by job id. Both are configured from the worker :class:`Settings`.

Task *implementations* live in :mod:`promptforge_worker.tasks`; ``include`` below makes
the worker import them at startup so they register. The API never imports this module —
it enqueues by task name via ``send_task`` (see the API-side producer), so the two
packages stay decoupled.
"""

from celery import Celery
from kombu import Queue

# Imported for the side effect of its @signal.connect decorators (correlation-id binding);
# nothing here references it. signals.py imports no app, so there's no cycle — top-level.
from promptforge_worker import signals  # noqa: F401
from promptforge_worker.config import get_settings
from promptforge_worker.logging_config import configure_logging

# Queue names. Heavy/slow work (evals) and fast work (scans) get separate queues so a
# backlog of slow jobs can't starve quick ones. The default queue carries everything else
# (e.g. the health ping). In v0.1 a single worker drains all three; the point of the split
# is that prod can run a dedicated worker per queue (`celery worker -Q evals`).
DEFAULT_QUEUE = "celery"
EVALS_QUEUE = "evals"
SCANS_QUEUE = "scans"
# Traces are high-volume, low-cost telemetry; their own queue keeps a burst of trace
# ingests from delaying the slow eval/scan jobs (and lets prod dedicate a worker to them).
TRACES_QUEUE = "traces"

settings = get_settings()
configure_logging(settings)

app = Celery(
    settings.app_name,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Import task modules at startup so their @app.task registrations take effect.
    include=["promptforge_worker.tasks"],
)
app.conf.update(
    # JSON-only payloads: human-readable on the wire (Flower/redis-cli) and refuses
    # the pickle deserialization-RCE foot-gun. Producers must send JSON-safe args.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timestamps in UTC; the app layer localises if it ever needs to.
    timezone="UTC",
    enable_utc=True,
    # Emit a STARTED state (not just PENDING→SUCCESS) so a poller can tell "queued"
    # from "running" — useful for the eval/scan dashboards later.
    task_track_started=True,
    # Results are a polling convenience, not a system of record — expire them so a
    # busy queue can't grow Redis unbounded. One hour is plenty to read a job id back.
    result_expires=3600,
    # Celery 5.3+ no longer retries the initial broker connection by default; in compose
    # the worker may boot a beat before Redis is ready, so re-enable startup retries.
    broker_connection_retry_on_startup=True,
    # Don't let Celery recapture stdout/stderr and re-log it at WARNING — our structlog
    # writes JSON straight to stdout, and recapture both garbles the level and double-logs.
    worker_redirect_stdouts=False,
    # Emit task lifecycle events (sent/received/started/succeeded/retried) so Flower can
    # show task history and the retry→success timeline. Off by default; required for the
    # Sprint 6 demo. Small per-task overhead — one extra event message per transition.
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Concurrency model (ADR): a *threads* pool, because our tasks are I/O-bound (LLM
    # calls, scans) and the GIL releases on I/O, so threads give real concurrency cheaply.
    # Threads also need no os.fork(), so the SAME pool runs on Windows (local) and Linux
    # (compose) — no prefork/--pool=solo split. CPU-bound work would need prefork instead.
    worker_pool="threads",
    worker_concurrency=settings.worker_concurrency,
    # Queue topology + routing. Tasks are routed by name pattern to the right queue; the
    # default queue catches anything unrouted. Declaring the queues here means the broker
    # has them ready and a worker with no -Q drains all of them.
    task_default_queue=DEFAULT_QUEUE,
    task_queues=(
        Queue(DEFAULT_QUEUE),
        Queue(EVALS_QUEUE),
        Queue(SCANS_QUEUE),
        Queue(TRACES_QUEUE),
    ),
    task_routes={
        "promptforge.eval.*": {"queue": EVALS_QUEUE},
        "promptforge.scan.*": {"queue": SCANS_QUEUE},
        "promptforge.trace.*": {"queue": TRACES_QUEUE},
    },
)
