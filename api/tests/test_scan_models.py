"""Integration tests for the SecurityScan model against a real throwaway Postgres.

Same approach as test_eval_models: run the actual migration (the ``engine`` fixture does
``upgrade head``) and round-trip rows, so model/migration drift, a broken FK ondelete, or a
mis-stated CHECK shows up here rather than in production.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.scanning import Category, Finding, Severity


def _make_version(session: Session) -> PromptVersion:
    prompt = Prompt(name=f"greeter-{uuid.uuid4()}")
    prompt.versions.append(PromptVersion(version_number=1, content="Hello {{name}}"))
    session.add(prompt)
    session.flush()
    return prompt.versions[0]


def test_completed_scan_with_findings_round_trips(db_session: Session) -> None:
    version = _make_version(db_session)
    findings = [
        Finding(
            category=Category.SECRET,
            severity=Severity.HIGH,
            detector="aws_access_key_id",
            message="Possible AWS access key id",
            evidence="AKIA…XMPL",
            span=(5, 25),
        ).to_dict()
    ]
    scan = SecurityScan(
        prompt_version_id=version.id,
        scanners=["secret", "pii", "injection", "jailbreak"],
        status="completed",
        risk_level="high",
        findings=findings,
    )
    db_session.add(scan)
    db_session.flush()
    db_session.expire_all()  # force a re-read from the DB, not the identity map

    fetched = db_session.scalars(select(SecurityScan).where(SecurityScan.id == scan.id)).one()
    assert fetched.created_at is not None  # server default fired
    assert fetched.risk_level == "high"
    assert fetched.scanners == ["secret", "pii", "injection", "jailbreak"]  # JSONB round-trips
    assert fetched.findings is not None
    restored = Finding.from_dict(fetched.findings[0])
    assert restored.detector == "aws_access_key_id"
    assert restored.span == (5, 25)


def test_clean_scan_has_empty_findings_and_none_risk(db_session: Session) -> None:
    scan = SecurityScan(scanners=["secret"], status="completed", risk_level="none", findings=[])
    db_session.add(scan)
    db_session.flush()
    db_session.expire_all()

    fetched = db_session.get(SecurityScan, scan.id)
    assert fetched is not None
    assert fetched.findings == []
    assert fetched.risk_level == "none"


def test_ad_hoc_scan_persists_without_a_version(db_session: Session) -> None:
    # The DoD's "paste a prompt": a scan of free text is tied to no prompt version.
    scan = SecurityScan(scanners=["secret"], status="pending")
    db_session.add(scan)
    db_session.flush()

    fetched = db_session.get(SecurityScan, scan.id)
    assert fetched is not None
    assert fetched.prompt_version_id is None
    assert fetched.risk_level is None  # not set until completion


def test_deleting_a_version_nulls_the_scan_pointer_but_keeps_the_scan(db_session: Session) -> None:
    version = _make_version(db_session)
    scan = SecurityScan(
        prompt_version_id=version.id, scanners=["secret"], status="completed", risk_level="none"
    )
    db_session.add(scan)
    db_session.flush()

    db_session.delete(version)
    db_session.flush()
    db_session.expire_all()

    # SET NULL: the historical scan result survives the version being deleted.
    fetched = db_session.get(SecurityScan, scan.id)
    assert fetched is not None
    assert fetched.prompt_version_id is None


def test_scan_status_defaults_to_pending(db_session: Session) -> None:
    scan = SecurityScan(scanners=["secret"])
    db_session.add(scan)
    db_session.flush()
    db_session.expire_all()
    fetched = db_session.get(SecurityScan, scan.id)
    assert fetched is not None
    assert fetched.status == "pending"


def test_invalid_status_is_rejected(db_session: Session) -> None:
    db_session.add(SecurityScan(scanners=["secret"], status="banana"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_invalid_risk_level_is_rejected(db_session: Session) -> None:
    db_session.add(SecurityScan(scanners=["secret"], status="completed", risk_level="critical"))
    with pytest.raises(IntegrityError):
        db_session.flush()
