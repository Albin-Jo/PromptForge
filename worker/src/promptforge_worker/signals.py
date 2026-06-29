"""Celery signal handlers that thread the correlation id into task execution.

The API binds a ``request_id`` per request (RequestIDMiddleware) and injects it into the
task's headers when it enqueues (the producer-side ``before_task_publish`` handler). Here,
on the **worker** side, we lift that id off the incoming task and bind it to structlog's
contextvars for the duration of the task — so every log line a task emits carries the same
``request_id`` as the request that submitted it, with no manual threading. The end-of-task
handler clears it so ids never leak between tasks on a reused worker process.
"""

from typing import Any

import structlog
from celery.signals import task_postrun, task_prerun

REQUEST_ID_HEADER = "request_id"


@task_prerun.connect
def bind_request_id(task: Any = None, **_: Any) -> None:
    """Bind the inbound request id (if any) to this task's logging context."""
    structlog.contextvars.clear_contextvars()
    # Custom headers set at publish time are exposed on the task's request object.
    request_id = getattr(task.request, REQUEST_ID_HEADER, None) if task is not None else None
    if request_id:
        structlog.contextvars.bind_contextvars(request_id=request_id)


@task_postrun.connect
def clear_request_id(**_: Any) -> None:
    """Clear the logging context so the id can't bleed into the next task."""
    structlog.contextvars.clear_contextvars()
