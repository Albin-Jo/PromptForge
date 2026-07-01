"""Integration test: a high-severity scan blocks promotion, end-to-end over HTTP + Postgres.

The Sprint 12 DoD's "high-severity can block promotion", through the real stack (router → service
→ gate → DB), the way Sprint 11's gate test covers the eval block. The decision logic is unit-
tested with fakes elsewhere; here we prove the *wiring* in **block** mode: a refused promotion
returns 409 with the security detail, writes a ``blocked`` audit, fires a webhook, and leaves the
label unmoved. The eval gate is irrelevant here — the security check runs first and independently,
so no golden set is needed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.cache import NullCache
from promptforge_api.db.audit_models import AuditEvent
from promptforge_api.db.engine import get_session
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.main import create_app
from promptforge_api.promotion import PromotionPolicy
from promptforge_api.repositories.audit import AuditRepository
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.repositories.evals import EvalRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.repositories.scans import ScanRepository
from promptforge_api.routers import prompts as prompts_router
from promptforge_api.scanning import Category, Finding, Severity
from promptforge_api.security_gate import SecurityGatePolicy
from promptforge_api.services.evals import EvalService
from promptforge_api.services.promotion import PromotionGate
from promptforge_api.services.prompts import PromptService
from promptforge_api.services.scans import ScanService

_BLOCK_POLICY = SecurityGatePolicy(mode="block", block_severity=Severity.HIGH)
_EVAL_POLICY = PromotionPolicy(
    gated_label="production", min_quality=0.7, max_quality_drop=0.05, min_dataset_size=3
)


@pytest.fixture
def block_client(db_session: Session, recorders: SimpleNamespace) -> Iterator[TestClient]:
    """A TestClient whose gate runs the security check in BLOCK mode, with recorder side effects."""

    def _override_session() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    def _scan_service() -> ScanService:
        return ScanService(
            ScanRepository(db_session),
            PromptRepository(db_session),
            submit_scan=recorders.scans.append,
        )

    def override_prompt_service() -> PromptService:
        gate = PromotionGate(
            EvalService(
                EvalRepository(db_session),
                PromptRepository(db_session),
                submit_eval=recorders.evals.append,
            ),
            AuditRepository(db_session),
            policy=_EVAL_POLICY,
            submit_webhook=recorders.webhooks.append,
            scans=_scan_service(),
            security_policy=_BLOCK_POLICY,
        )
        return PromptService(
            PromptRepository(db_session),
            NullCache(),
            composition=CompositionRepository(db_session),
            gate=gate,
            scans=_scan_service(),
        )

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[prompts_router.get_prompt_service] = override_prompt_service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def recorders() -> SimpleNamespace:
    return SimpleNamespace(scans=[], evals=[], webhooks=[])


def _complete_scan(session: Session, version_id: uuid.UUID, risk_level: str) -> None:
    """Seed a completed scan at *risk_level* for a version (the worker would write this)."""
    finding = Finding(
        category=Category.SECRET,
        severity=Severity.HIGH,
        detector="aws_access_key_id",
        message="Possible AWS access key id",
        evidence="AKIA…XMPL",
    ).to_dict()
    session.add(
        SecurityScan(
            prompt_version_id=version_id,
            scanners=["secret"],
            status="completed",
            risk_level=risk_level,
            findings=[finding],
        )
    )
    session.flush()


def test_high_risk_scan_blocks_promotion(
    block_client: TestClient, db_session: Session, recorders: SimpleNamespace
) -> None:
    created = block_client.post(
        "/prompts", json={"name": "leaky", "content": "key AKIA…", "input_variables": []}
    )
    assert created.status_code == 201, created.text
    v1_id = created.json()["versions"][0]["id"]
    _complete_scan(db_session, uuid.UUID(v1_id), "high")

    resp = block_client.put("/prompts/leaky/labels/production", json={"version_number": 1})

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["promotion"]["security"] is True
    assert body["promotion"]["risk_level"] == "high"

    # a blocked audit was written...
    blocked = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "blocked")
    ).all()
    assert len(blocked) == 1
    # ...a webhook fired...
    assert any(w["event"] == "promotion.blocked" for w in recorders.webhooks)
    # ...and the label never moved (no production label exists).
    assert block_client.get("/prompts/leaky/labels/production").status_code == 404


def test_clean_scan_does_not_security_block(block_client: TestClient, db_session: Session) -> None:
    """A 'none'-risk scan must pass the security gate (then it's the eval gate's call, not ours)."""
    created = block_client.post(
        "/prompts", json={"name": "clean", "content": "be helpful", "input_variables": []}
    )
    v1_id = created.json()["versions"][0]["id"]
    _complete_scan(db_session, uuid.UUID(v1_id), "none")

    resp = block_client.put("/prompts/clean/labels/production", json={"version_number": 1})

    # Security let it through, so the request falls to the eval gate, which refuses for a
    # *different* reason: no golden set (409). The point: the refusal is NOT a security block.
    assert resp.status_code == 409
    body = resp.json()
    assert "golden set" in body["detail"].lower()
    assert "promotion" not in body  # not a gate-decision block; just the missing-golden-set error
