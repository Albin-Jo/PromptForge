"""Worker task definitions.

Two tasks: a trivial ``ping`` (proves the broker→worker path) and the real ``run_eval``,
which executes a full evaluation off the request path.

``run_eval`` (Sprint 8) replaces the Sprint 6 *stub* and its Redis dedup store: idempotency now
keys on the **eval run row itself** — a run already ``completed`` short-circuits — which is the
DB-backed guard the Sprint 6 ADR always pointed to (the run table is the system of record). The
heavy lifting (generate → score → persist → aggregate) lives in :class:`EvalRunner`; this module
owns only the task wiring and the run's status lifecycle.

Task **names** are explicit, namespaced constants. The API enqueues by this string (it never
imports this module), so the name is the producer/consumer contract — keep it the single source
of truth here and mirror it on the API side (``promptforge_api.celery_client``).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from celery import Task

from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.gateway import LLMGateway
from promptforge_api.observability import TraceEvent, persist_trace
from promptforge_worker.celery_app import app
from promptforge_worker.db import session_scope
from promptforge_worker.errors import TransientEvalError, TransientScanError, TransientWebhookError
from promptforge_worker.evals.runner import EvalRunner, EvalRunNotFoundError
from promptforge_worker.scanning.runner import ScanNotFoundError, ScanRunner

log = structlog.get_logger(__name__)

# The producer/consumer contract. Namespaced so routing + Flower stay legible.
PING_TASK = "promptforge.health.ping"
RUN_EVAL_TASK = "promptforge.eval.run"
RUN_SCAN_TASK = "promptforge.scan.run"
TRACE_INGEST_TASK = "promptforge.trace.ingest"
DELIVER_WEBHOOK_TASK = "promptforge.webhook.deliver"

# Bound the time we'll wait on a receiver before treating the POST as transiently failed.
_WEBHOOK_TIMEOUT_SECONDS = 10


@lru_cache
def get_gateway() -> LLMGateway:
    """The process-wide gateway for eval generation + judge scoring.

    Cached so one connection-pool/resilience config is shared across tasks. Defaults to the real
    ``litellm.acompletion`` backend; tests monkeypatch this accessor to inject a fake gateway,
    keeping the suite off the network (mirrors how the judge takes its gateway by injection).
    """
    return LLMGateway()


@app.task(name=PING_TASK)
def ping() -> dict[str, str]:
    """Return a static payload — a smoke test that the broker→worker path works."""
    log.info("ping_received")
    return {"status": "ok"}


@app.task(
    name=TRACE_INGEST_TASK,
    # At-least-once: ack after the row is written, so a worker crash mid-ingest redelivers.
    # persist_trace is idempotent on the trace id, so redelivery never double-counts spend.
    acks_late=True,
    task_reject_on_worker_lost=True,
)
def ingest_trace(payload: dict[str, Any]) -> dict[str, str]:
    """Write one emitted execution to the ``traces`` table, off the request path.

    The payload is a :class:`~promptforge_api.observability.TraceEvent` as a dict (the queue
    contract). We rebuild the event, compute its cost, and insert it idempotently. A bad
    payload (missing ``model``/``status``) raises and the task is recorded failed — a single
    malformed trace is telemetry we drop, never something that should retry forever.
    """
    event = TraceEvent.from_dict(payload)
    with session_scope() as session:
        persist_trace(session, event)
    return {"status": "ingested", "trace_id": str(event.id)}


@app.task(
    bind=True,
    name=RUN_EVAL_TASK,
    # Ack only AFTER the task returns, so a worker crash mid-run redelivers it (at-least-once).
    # The run-status idempotency guard below makes that redelivery safe.
    acks_late=True,
    task_reject_on_worker_lost=True,
    # Auto-retry only failures we explicitly classify as transient; everything else fails fast.
    autoretry_for=(TransientEvalError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def run_eval(self: Task, *, eval_run_id: str) -> dict[str, Any]:
    """Run one evaluation to completion: generate outputs, score them, store per-item + summary.

    Idempotent on ``eval_run_id`` and safe against concurrent duplicates. The whole run — claim,
    generate, score, persist, status flip — is **one transaction holding a row lock** on the run
    (``with_for_update``):

    - *Sequential redelivery* of an already-``completed`` run returns its stored summary, no rework.
    - *Concurrent duplicates* serialize on the lock: the second delivery blocks until the first
      commits, then sees ``completed`` and skips — so scores are never double-written.
    - *A crash mid-run* never commits, so the row rolls back to ``pending`` (no stuck ``running``)
      and ``acks_late`` redelivery re-runs cleanly.

    The cost is that the row lock is held for the run's duration; that's fine here because plain
    reads don't block on it in Postgres, and the only writer that contends is the exact duplicate
    we mean to dedupe. The trade is that status goes ``pending → completed`` in one commit, so a
    transient mid-run ``running`` state isn't separately observable (acceptable for v0.1).
    """
    run_id = uuid.UUID(eval_run_id)

    try:
        with session_scope() as session:
            # Lock the run row for the whole transaction (see docstring): this is the idempotency
            # + concurrency guard. A second concurrent task blocks here until we commit.
            run = session.get(EvalRun, run_id, with_for_update=True)
            if run is None:
                raise EvalRunNotFoundError(f"eval run {eval_run_id} not found")
            if run.status == "completed":
                log.info("eval_idempotent_skip", eval_run_id=eval_run_id)
                return {
                    "status": "completed",
                    "eval_run_id": eval_run_id,
                    "summary": run.summary,
                    "deduplicated": True,
                }
            summary = asyncio.run(EvalRunner(get_gateway()).run(session, run))
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
        log.info("eval_completed", eval_run_id=eval_run_id)
        return {"status": "completed", "eval_run_id": eval_run_id, "summary": summary}
    except TransientEvalError:
        # Scores rolled back with the failed transaction; let the task retry the whole run.
        log.warning("eval_transient_failure", eval_run_id=eval_run_id)
        raise
    except Exception:
        # Permanent failure: the work transaction rolled back (status is still pending), so mark
        # the run failed in a fresh transaction, then surface it so the task is recorded failed.
        log.exception("eval_failed", eval_run_id=eval_run_id)
        with session_scope() as session:
            run = session.get(EvalRun, run_id, with_for_update=True)
            if run is not None and run.status != "completed":
                run.status = "failed"
        raise


@app.task(
    bind=True,
    name=RUN_SCAN_TASK,
    # Same at-least-once + idempotency story as run_eval: ack after the task returns so a crash
    # mid-scan redelivers, and the scan-row lock below makes that redelivery safe.
    acks_late=True,
    task_reject_on_worker_lost=True,
    autoretry_for=(TransientScanError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def run_scan(self: Task, *, security_scan_id: str) -> dict[str, Any]:
    """Run one security scan to completion: scan the version's text, persist findings + risk level.

    Idempotent on ``security_scan_id`` and safe against concurrent duplicates, by the exact same
    mechanism as :func:`run_eval` — the whole scan (claim, scan, persist, status flip) is one
    transaction holding a row lock (``with_for_update``) on the scan row:

    - redelivery of an already-``completed`` scan returns its stored summary, no rework;
    - concurrent duplicates serialize on the lock, so findings are never double-written;
    - a crash mid-scan never commits, so the row rolls back to ``pending`` and redelivery re-runs.
    """
    scan_id = uuid.UUID(security_scan_id)

    try:
        with session_scope() as session:
            scan = session.get(SecurityScan, scan_id, with_for_update=True)
            if scan is None:
                raise ScanNotFoundError(f"security scan {security_scan_id} not found")
            if scan.status == "completed":
                log.info("scan_idempotent_skip", security_scan_id=security_scan_id)
                return {
                    "status": "completed",
                    "security_scan_id": security_scan_id,
                    "risk_level": scan.risk_level,
                    "deduplicated": True,
                }
            summary = asyncio.run(ScanRunner(get_gateway()).run(session, scan))
            scan.status = "completed"
            scan.completed_at = datetime.now(UTC)
        log.info("scan_finished", security_scan_id=security_scan_id)
        return {"status": "completed", "security_scan_id": security_scan_id, "summary": summary}
    except TransientScanError:
        # Findings rolled back with the failed transaction; let the task retry the whole scan.
        log.warning("scan_transient_failure", security_scan_id=security_scan_id)
        raise
    except Exception:
        # Permanent failure: the work transaction rolled back (status still pending), so mark the
        # scan failed in a fresh transaction, then surface it so the task is recorded failed.
        log.exception("scan_failed", security_scan_id=security_scan_id)
        with session_scope() as session:
            scan = session.get(SecurityScan, scan_id, with_for_update=True)
            if scan is not None and scan.status != "completed":
                scan.status = "failed"
        raise


@app.task(
    name=DELIVER_WEBHOOK_TASK,
    # At-least-once delivery, the standard webhook contract: ack after the POST succeeds so a
    # crash mid-delivery redelivers. Receivers are expected to dedupe on the event payload.
    acks_late=True,
    task_reject_on_worker_lost=True,
    # Retry only failures we classify as transient (network error / receiver 5xx); a 4xx is a
    # permanent reject and fails fast. Backoff + jitter so a flapping receiver isn't hammered.
    autoretry_for=(TransientWebhookError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def deliver_webhook(
    payload: dict[str, Any], *, url: str, secret: str | None = None
) -> dict[str, Any]:
    """POST one promotion event to a subscriber's URL, off the request path.

    The body is the JSON ``payload`` built by the promotion gate. When *secret* is set, the body
    is signed with HMAC-SHA256 and sent as ``X-PromptForge-Signature: sha256=<hex>`` so the
    receiver can verify the call really came from us (and wasn't tampered with). Uses the stdlib
    HTTP client to keep the worker free of an extra dependency for a single POST.
    """
    event = payload.get("event")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "promptforge-webhook/1"}
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-PromptForge-Signature"] = f"sha256={signature}"

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_WEBHOOK_TIMEOUT_SECONDS) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        # The receiver answered with an error status. 5xx may be transient (retry); 4xx means it
        # rejected this payload and won't change its mind — log and stop.
        if exc.code >= 500:
            log.warning("webhook_retryable", webhook_event=event, status=exc.code)
            raise TransientWebhookError(f"receiver returned {exc.code}") from exc
        log.error("webhook_rejected", webhook_event=event, status=exc.code)
        return {"status": "rejected", "code": exc.code}
    except urllib.error.URLError as exc:
        # Couldn't reach the receiver at all (DNS/connection/timeout) — worth a retry.
        log.warning("webhook_unreachable", webhook_event=event, error=str(exc.reason))
        raise TransientWebhookError(f"could not reach webhook receiver: {exc.reason}") from exc

    log.info("webhook_delivered", webhook_event=event, status=status_code)
    return {"status": "delivered", "code": status_code}
