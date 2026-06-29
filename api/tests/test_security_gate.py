"""Unit tests for the pure security-gate decision rule (no I/O).

The orchestration (loading the scan, writing the audit, firing the webhook) is integration-tested
through the promotion gate; here we pin the policy logic: warn never blocks, block blocks at/above
the threshold, and 'none'/None never blocks.
"""

from __future__ import annotations

import pytest

from promptforge_api.scanning import Severity
from promptforge_api.security_gate import SecurityGatePolicy, risk_blocks

_BLOCK_HIGH = SecurityGatePolicy(mode="block", block_severity=Severity.HIGH)
_BLOCK_MEDIUM = SecurityGatePolicy(mode="block", block_severity=Severity.MEDIUM)
_WARN = SecurityGatePolicy(mode="warn", block_severity=Severity.HIGH)


@pytest.mark.parametrize("risk_level", [None, "none", "low", "medium", "high"])
def test_warn_mode_never_blocks(risk_level: str | None) -> None:
    assert risk_blocks(risk_level, _WARN) is False


@pytest.mark.parametrize(
    ("risk_level", "expected"),
    [(None, False), ("none", False), ("low", False), ("medium", False), ("high", True)],
)
def test_block_at_high(risk_level: str | None, expected: bool) -> None:
    assert risk_blocks(risk_level, _BLOCK_HIGH) is expected


@pytest.mark.parametrize(
    ("risk_level", "expected"), [("low", False), ("medium", True), ("high", True)]
)
def test_block_at_medium_includes_high(risk_level: str, expected: bool) -> None:
    # A lower threshold also blocks everything above it (severity is ordered).
    assert risk_blocks(risk_level, _BLOCK_MEDIUM) is expected


def test_policy_from_settings_maps_strings_to_severity() -> None:
    class _S:
        scan_gate_mode = "block"
        scan_gate_block_severity = "medium"

    policy = SecurityGatePolicy.from_settings(_S())  # type: ignore[arg-type]
    assert policy.mode == "block"
    assert policy.block_severity is Severity.MEDIUM
