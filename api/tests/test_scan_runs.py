"""Integration tests for the per-version scan run-history endpoint (Sprint 24, T2).

``GET /prompts/{name}/versions/{n}/scans`` lists every persisted security scan for a version,
newest first — the audit trail behind the latest-only ``/scan`` status. Note every version is
scanned on save (safety isn't opt-in), so a freshly created version already has one scan. A
completed scan is simulated by writing crafted findings (the worker does the real scanning).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptforge_api.db.scan_models import SecurityScan


def _create_prompt(client: TestClient, name: str) -> uuid.UUID:
    resp = client.post(
        "/prompts", json={"name": name, "content": "Say {{x}}", "input_variables": ["x"]}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["versions"][0]["id"])


def _complete_latest_scan(session: Session, prompt_version_id: uuid.UUID) -> None:
    """Mark a version's most recent scan completed with one crafted high-severity finding."""
    scan = session.scalars(
        select(SecurityScan)
        .where(SecurityScan.prompt_version_id == prompt_version_id)
        .order_by(SecurityScan.created_at.desc())
    ).first()
    assert scan is not None
    scan.status = "completed"
    scan.completed_at = datetime.now(UTC)
    scan.scanners = ["injection"]
    scan.risk_level = "high"
    scan.findings = [
        {
            "category": "injection",
            "severity": "high",
            "detector": "instruction-override",
            "message": "Possible prompt injection",
            "evidence": "ignore previous…",
            "span": None,
            "metadata": {},
        }
    ]
    session.flush()


def test_lists_scans_newest_first_with_findings(client: TestClient, db_session: Session) -> None:
    version_id = _create_prompt(client, "greeter")  # scan-on-save creates scan #1 (pending)
    assert client.post("/prompts/greeter/versions/1/scan").status_code == 202  # scan #2
    _complete_latest_scan(db_session, version_id)

    resp = client.get("/prompts/greeter/versions/1/scans")

    assert resp.status_code == 200, resp.text
    scans = resp.json()
    assert len(scans) == 2
    # Newest first: the completed scan leads, carrying its risk level + findings.
    assert scans[0]["status"] == "completed"
    assert scans[0]["risk_level"] == "high"
    assert len(scans[0]["findings"]) == 1
    assert scans[0]["findings"][0]["category"] == "injection"
    # The older scan-on-save is still pending and carries no findings yet.
    assert scans[1]["status"] == "pending"
    assert scans[1]["findings"] is None


def test_unknown_prompt_is_404(client: TestClient) -> None:
    assert client.get("/prompts/nope/versions/1/scans").status_code == 404


def test_unknown_version_is_404(client: TestClient) -> None:
    _create_prompt(client, "fresh")
    assert client.get("/prompts/fresh/versions/999/scans").status_code == 404
