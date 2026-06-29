"""Unit tests for the scanning domain types — no database, pure logic.

These pin the two behaviours the rest of the engine leans on: severity ordering/rollup
(``Severity.max_of`` feeds ``SecurityScan.risk_level``) and Finding ⇄ dict round-tripping
(the JSONB persistence contract). Scanner implementations get their own fixture-based tests
later; here we only test the shared vocabulary.
"""

from promptforge_api.scanning import Category, Finding, Severity


def test_severity_is_ordered_low_to_high() -> None:
    assert Severity.LOW.rank < Severity.MEDIUM.rank < Severity.HIGH.rank


def test_max_of_returns_the_worst_severity() -> None:
    assert Severity.max_of([Severity.LOW, Severity.HIGH, Severity.MEDIUM]) == Severity.HIGH


def test_max_of_empty_is_none() -> None:
    # A clean scan (no findings) has no severity to roll up — risk_level becomes "none".
    assert Severity.max_of([]) is None


def test_severity_is_its_string_value() -> None:
    # StrEnum: the member IS "high", so it serialises into JSONB with no .value dance needed.
    assert str(Severity.HIGH) == "high"
    assert Severity("high") is Severity.HIGH


def test_finding_round_trips_through_dict() -> None:
    finding = Finding(
        category=Category.SECRET,
        severity=Severity.HIGH,
        detector="aws_access_key_id",
        message="Possible AWS access key id",
        evidence="AKIA…XMPL",
        span=(10, 30),
        metadata={"entropy": 4.2},
    )
    restored = Finding.from_dict(finding.to_dict())
    assert restored == finding


def test_finding_to_dict_uses_json_safe_shapes() -> None:
    data = Finding(
        category=Category.INJECTION,
        severity=Severity.MEDIUM,
        detector="llm_judge",
        message="instruction-override attempt",
    ).to_dict()
    # span defaults to None (the judge reasons over the whole text); enums become plain strings.
    assert data["span"] is None
    assert data["category"] == "injection"
    assert data["severity"] == "medium"
    assert data["evidence"] == ""


def test_finding_from_dict_rebuilds_span_tuple() -> None:
    # JSON has no tuple — a stored span is a 2-element list; from_dict restores the tuple.
    restored = Finding.from_dict(
        {
            "category": "pii",
            "severity": "low",
            "detector": "email",
            "message": "email address",
            "span": [3, 19],
        }
    )
    assert restored.span == (3, 19)
    assert restored.category is Category.PII
