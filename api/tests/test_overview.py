"""Fleet-overview read-model (ADR 0022): the cross-prompt rollup + the "needs attention" rules.

Against a real throwaway Postgres, seed a small fleet whose prompts each trip a *different* rule,
then assert the fleet totals, the gap-filled trend, and each prompt's fired rule keys. Each prompt
is constructed so exactly one rule (or a known pair) fires, isolating the rule under test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.db.trace_models import Trace
from promptforge_api.repositories.metrics import MetricsRepository
from promptforge_api.repositories.overview import OverviewRepository
from promptforge_api.services.overview import (
    ATTENTION_EVAL,
    ATTENTION_HIGH_ERROR,
    ATTENTION_IDLE,
    ATTENTION_SCAN,
    OverviewService,
)


def _service(db_session: Session) -> OverviewService:
    return OverviewService(MetricsRepository(db_session), OverviewRepository(db_session))


def _trace(prompt_id: uuid.UUID, version_id: uuid.UUID, *, status: str = "ok") -> Trace:
    return Trace(
        prompt_id=prompt_id,
        prompt_version_id=version_id,
        model="openai/gpt-4o-mini",
        status=status,
        source="sdk",
        latency_ms=100,
        cost_usd=Decimal("0.001"),
        created_at=datetime.now(UTC),
    )


def _completed_eval(version_id: uuid.UUID, mean: float) -> EvalRun:
    return EvalRun(
        prompt_version_id=version_id,
        scorer_config=[],
        status="completed",
        summary={"scorers": {"judge": {"mean_value": mean}}},
        completed_at=datetime.now(UTC),
    )


def _completed_scan(version_id: uuid.UUID, risk: str) -> SecurityScan:
    return SecurityScan(
        prompt_version_id=version_id, scanners=[], status="completed", risk_level=risk
    )


@pytest.fixture
def fleet(db_session: Session) -> None:
    """Four prompts, each engineered to fire a specific attention rule (or known pair)."""
    # alpha: latest v2, healthy eval + scan, but a 20% error rate → only high_error_rate.
    alpha = Prompt(name="alpha")
    alpha.versions.append(PromptVersion(version_number=1, content="a"))
    alpha.versions.append(PromptVersion(version_number=2, content="b"))
    # beta: single version, no traffic, no eval, no scan → eval + scan (not idle: one version).
    beta = Prompt(name="beta")
    beta.versions.append(PromptVersion(version_number=1, content="a"))
    # gamma: two versions, healthy eval + scan, but zero traffic → only no_recent_traffic.
    gamma = Prompt(name="gamma")
    gamma.versions.append(PromptVersion(version_number=1, content="a"))
    gamma.versions.append(PromptVersion(version_number=2, content="b"))
    # delta: single version, traffic but low quality + a high-risk scan → eval + scan.
    delta = Prompt(name="delta")
    delta.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add_all([alpha, beta, gamma, delta])
    db_session.flush()

    a2, g2, d1 = alpha.versions[1].id, gamma.versions[1].id, delta.versions[0].id

    db_session.add_all(
        # alpha: 8 ok + 2 error = 20% error rate.
        [_trace(alpha.id, a2) for _ in range(8)]
        + [_trace(alpha.id, a2, status="error") for _ in range(2)]
        # delta: 5 ok, no errors.
        + [_trace(delta.id, d1) for _ in range(5)]
    )
    db_session.add_all(
        [
            _completed_eval(a2, 0.9),  # alpha healthy
            _completed_eval(g2, 0.9),  # gamma healthy
            _completed_eval(d1, 0.3),  # delta failing (< 0.5)
        ]
    )
    db_session.add_all(
        [
            _completed_scan(a2, "none"),  # alpha clean
            _completed_scan(g2, "none"),  # gamma clean
            _completed_scan(d1, "high"),  # delta risky
        ]
    )
    db_session.flush()


def _by_name(overview: object) -> dict[str, object]:
    return {p.name: p for p in overview.prompts}  # type: ignore[attr-defined]


def test_fleet_totals_sum_across_prompts(fleet: None, db_session: Session) -> None:
    overview = _service(db_session).fleet_overview(window="7d")
    # 10 alpha + 5 delta = 15 requests, 2 errors.
    assert overview.totals.request_count == 15
    assert overview.totals.error_count == 2
    assert overview.totals.error_rate == pytest.approx(2 / 15)
    assert overview.totals.total_cost_usd == Decimal("0.015")


def test_fleet_totals_include_unlinked_traffic(fleet: None, db_session: Session) -> None:
    """Fleet totals/trend are platform-wide: they count traffic with no prompt link (ad-hoc gateway
    calls), which the per-prompt rollup cannot attribute to a row. So totals can exceed the sum of
    the rows by exactly that unlinked traffic — documented and intended (services/overview.py)."""
    db_session.add(
        Trace(
            prompt_id=None,
            prompt_version_id=None,
            model="openai/gpt-4o-mini",
            status="ok",
            source="gateway",
            latency_ms=100,
            cost_usd=Decimal("0.001"),
            created_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    overview = _service(db_session).fleet_overview(window="7d")
    # 15 prompt-linked + 1 unlinked = 16 in the totals...
    assert overview.totals.request_count == 16
    # ...but the per-prompt rows only see the 15 they can attribute.
    assert sum(p.request_count for p in overview.prompts) == 15


def test_trend_is_present_and_gap_filled(fleet: None, db_session: Session) -> None:
    overview = _service(db_session).fleet_overview(window="7d")
    assert overview.interval == "day"
    # A daily 7d window yields a contiguous spine (≥7 buckets), with today carrying all 15 requests.
    assert len(overview.trend) >= 7
    assert sum(b.request_count for b in overview.trend) == 15
    # Empty days are present with a real 0, not dropped.
    assert any(b.request_count == 0 for b in overview.trend)


def test_high_error_rate_rule(fleet: None, db_session: Session) -> None:
    alpha = _by_name(_service(db_session).fleet_overview(window="7d"))["alpha"]
    assert alpha.attention == [ATTENTION_HIGH_ERROR]  # type: ignore[attr-defined]
    assert alpha.error_rate == pytest.approx(0.2)  # type: ignore[attr-defined]
    assert alpha.latest_version == 2  # type: ignore[attr-defined]


def test_missing_eval_and_scan_rules(fleet: None, db_session: Session) -> None:
    beta = _by_name(_service(db_session).fleet_overview(window="7d"))["beta"]
    # No eval and no scan on the latest version → both fire; one version → not idle.
    assert set(beta.attention) == {ATTENTION_EVAL, ATTENTION_SCAN}  # type: ignore[attr-defined]
    assert ATTENTION_IDLE not in beta.attention  # type: ignore[attr-defined]


def test_no_recent_traffic_rule_only_for_established_prompts(
    fleet: None, db_session: Session
) -> None:
    gamma = _by_name(_service(db_session).fleet_overview(window="7d"))["gamma"]
    # Healthy eval + scan, two versions, zero traffic → only idle fires.
    assert gamma.attention == [ATTENTION_IDLE]  # type: ignore[attr-defined]


def test_low_quality_and_risky_scan_rules(fleet: None, db_session: Session) -> None:
    delta = _by_name(_service(db_session).fleet_overview(window="7d"))["delta"]
    # Failing eval (0.3 < 0.5) and a high-risk scan → eval + scan; traffic clean so no high_error.
    assert set(delta.attention) == {ATTENTION_EVAL, ATTENTION_SCAN}  # type: ignore[attr-defined]
    assert ATTENTION_HIGH_ERROR not in delta.attention  # type: ignore[attr-defined]
    assert delta.quality == pytest.approx(0.3)  # type: ignore[attr-defined]


# --------------------------------------------------------------------- HTTP surface
def test_overview_endpoint_shape_and_string_money(fleet: None, client: TestClient) -> None:
    body = client.get("/overview", params={"window": "7d"}).json()

    assert body["window"] == "7d"
    assert body["interval"] == "day"
    assert body["totals"]["request_count"] == 15
    assert body["totals"]["total_cost_usd"] == "0.015000"  # exact string, not a float
    names = {p["name"] for p in body["prompts"]}
    assert names == {"alpha", "beta", "gamma", "delta"}
    alpha = next(p for p in body["prompts"] if p["name"] == "alpha")
    assert alpha["attention"] == ["high_error_rate"]


def test_overview_endpoint_empty_fleet(client: TestClient) -> None:
    body = client.get("/overview").json()
    assert body["totals"]["request_count"] == 0
    assert body["totals"]["error_rate"] is None  # no faked 0 over an empty fleet
    assert body["prompts"] == []


def test_overview_endpoint_422_for_bad_window(client: TestClient) -> None:
    assert client.get("/overview", params={"window": "1y"}).status_code == 422
