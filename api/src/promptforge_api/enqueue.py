"""Composition helpers that wire the services' enqueue callables to the Celery producer.

The eval and promotion services take their "enqueue side" by injection — a plain callable —
so they never import Celery and a test can pass a recorder instead. These are the *production*
implementations the routers inject: thin adapters from a domain call (run this eval / deliver
this event) to ``celery_client``. Kept out of the routers so the wiring lives in one place, and
out of ``celery_client`` so that module stays a pure transport client.
"""

from __future__ import annotations

import uuid
from typing import Any

from promptforge_api import celery_client
from promptforge_api.config import Settings
from promptforge_api.services.promotion import WebhookSubmit


def submit_eval(eval_run_id: uuid.UUID) -> None:
    """Enqueue a gating eval run (return value discarded — the run id is the system of record)."""
    celery_client.enqueue_eval(eval_run_id)


def submit_scan(security_scan_id: uuid.UUID) -> None:
    """Enqueue a security scan (return value discarded — the scan id is the system of record)."""
    celery_client.enqueue_scan(security_scan_id)


def make_webhook_submit(settings: Settings) -> WebhookSubmit:
    """Build the webhook-delivery callable, or a no-op when no webhook URL is configured.

    The gate always calls its ``submit_webhook``; whether anything is actually sent is decided
    here (config), so the gate stays ignorant of how/whether delivery happens.
    """
    url = settings.promotion_webhook_url
    if not url:

        def _noop(_payload: dict[str, Any]) -> None:
            return None

        return _noop

    secret = settings.promotion_webhook_secret

    def _submit(payload: dict[str, Any]) -> None:
        celery_client.enqueue_webhook(payload, url=url, secret=secret)

    return _submit
