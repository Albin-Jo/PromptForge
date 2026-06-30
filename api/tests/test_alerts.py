"""Drift/regression alerts: 'evaluate the evaluator' + a light endpoint check.

The evaluator is a pure function, so most of this hands it fabricated :class:`PromptMetrics` and
asserts the exact alerts — no DB needed. The endpoint test seeds a quality regression against a real
Postgres and confirms it surfaces over HTTP.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.trace_models import Trace
from promptforge_api.repositories.metrics import (
    LatencyPercentiles,
    MetricsBlock,
    SourceCost,
    VersionMetrics,
)
from promptforge_api.services.alerts import AlertPolicy, evaluate_alerts
from promptforge_api.services.metrics import PromptMetrics

_POLICY = AlertPolicy(
    min_quality=0.7,
    max_error_rate=0.1,
    max_cost_per_request_usd=Decimal("0.05"),
    max_quality_drop=0.1,
    min_requests=20,
)


def _block(*, n: int = 0, error_rate: float | None = None, cost: str | None = None) -> MetricsBlock:
    return MetricsBlock(
        request_count=n,
        error_count=0,
        error_rate=error_rate,
        latency=LatencyPercentiles(None, None, None),
        total_cost_usd=Decimal(cost) if cost is not None else None,
    )


def _version(version_number: int, quality: float | None, *, n: int = 100) -> VersionMetrics:
    return VersionMetrics(
        version_number=version_number,
        prompt_version_id=uuid.uuid4(),
        metrics=_block(n=n),
        quality=quality,
    )


def _metrics(
    *, overall: MetricsBlock | None = None, versions: tuple[VersionMetrics, ...] = ()
) -> PromptMetrics:
    return PromptMetrics(
        name="p",
        prompt_id=uuid.uuid4(),
        window="7d",
        since=datetime.now(UTC),
        overall=overall or _block(),
        by_version=list(versions),
        by_source=[SourceCost(source="sdk", cost_usd=None)],
    )


def test_healthy_metrics_fire_no_alerts() -> None:
    metrics = _metrics(
        overall=_block(n=100, error_rate=0.0, cost="0.10"),  # 0.001/req, well under 0.05
        versions=(_version(1, 0.9), _version(2, 0.92)),
    )
    assert evaluate_alerts(metrics, _POLICY) == []


def test_error_rate_above_threshold_fires() -> None:
    metrics = _metrics(overall=_block(n=100, error_rate=0.2))
    alerts = evaluate_alerts(metrics, _POLICY)
    assert [a.kind for a in alerts] == ["error_rate_high"]
    assert alerts[0].scope == "overall"
    assert alerts[0].observed == 0.2


def test_traffic_signals_suppressed_below_min_requests() -> None:
    # A wild error rate on only 5 requests must NOT fire — too little data to trust.
    metrics = _metrics(overall=_block(n=5, error_rate=0.9))
    assert evaluate_alerts(metrics, _POLICY) == []


def test_cost_per_request_above_threshold_fires() -> None:
    # $10 over 100 requests = $0.10/req > $0.05.
    metrics = _metrics(overall=_block(n=100, error_rate=0.0, cost="10"))
    alerts = evaluate_alerts(metrics, _POLICY)
    assert [a.kind for a in alerts] == ["cost_per_request_high"]
    assert alerts[0].observed == 0.1


def test_quality_below_threshold_fires_per_version() -> None:
    metrics = _metrics(versions=(_version(1, 0.5),))
    alerts = evaluate_alerts(metrics, _POLICY)
    assert [(a.kind, a.scope) for a in alerts] == [("quality_below_threshold", "version:1")]


def test_quality_regression_fires_against_previous_version() -> None:
    # 0.90 -> 0.75 is a 0.15 drop (> 0.10). 0.75 is above the 0.70 floor, so ONLY a regression.
    metrics = _metrics(versions=(_version(1, 0.90), _version(2, 0.75)))
    alerts = evaluate_alerts(metrics, _POLICY)
    assert [(a.kind, a.scope) for a in alerts] == [("quality_regression", "version:2")]


def test_quality_is_not_gated_by_min_requests() -> None:
    # Quality comes from a deliberate eval, so it fires even on a barely-trafficked version.
    metrics = _metrics(versions=(_version(1, 0.5, n=1),))
    assert [a.kind for a in evaluate_alerts(metrics, _POLICY)] == ["quality_below_threshold"]


def test_unevaluated_version_is_skipped() -> None:
    metrics = _metrics(versions=(_version(1, None), _version(2, None)))
    assert evaluate_alerts(metrics, _POLICY) == []


# --------------------------------------------------------------------- HTTP surface
def test_alerts_endpoint_surfaces_a_quality_breach(db_session: Session, client: TestClient) -> None:
    prompt = Prompt(name="alerting")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()
    v1 = prompt.versions[0].id

    # One trace (so v1 appears in by_version) + a completed eval whose mean is below the 0.7 floor.
    db_session.add(
        Trace(
            prompt_id=prompt.id,
            prompt_version_id=v1,
            model="openai/gpt-4o-mini",
            status="ok",
            source="sdk",
            latency_ms=100,
            cost_usd=Decimal("0.001"),
            created_at=datetime.now(UTC),
        )
    )
    db_session.add(
        EvalRun(
            prompt_version_id=v1,
            scorer_config=[],
            status="completed",
            summary={"scorers": {"judge": {"mean_value": 0.5}}},
            completed_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    body = client.get("/prompts/alerting/alerts").json()
    assert body["name"] == "alerting"
    kinds = [(a["kind"], a["scope"]) for a in body["alerts"]]
    assert ("quality_below_threshold", "version:1") in kinds


def test_alerts_endpoint_healthy_prompt_returns_empty(
    db_session: Session, client: TestClient
) -> None:
    prompt = Prompt(name="calm")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()

    body = client.get("/prompts/calm/alerts").json()
    assert body["alerts"] == []


def test_alerts_endpoint_404_for_unknown_prompt(client: TestClient) -> None:
    assert client.get("/prompts/nope/alerts").status_code == 404


# --------------------------------------------------------------------- alert policy read
def test_alert_policy_returns_configured_thresholds(client: TestClient) -> None:
    response = client.get("/alert-policy")
    assert response.status_code == 200
    body = response.json()

    # Flat, *global* shape only — no per-prompt identity fields leak in (ADR 0026).
    assert set(body) == {"thresholds"}

    # key -> (value, unit) must match the documented config defaults; ``unit`` is what tells the
    # UI which formatter to apply (score / ratio / usd / count).
    by_key = {t["key"]: (t["value"], t["unit"]) for t in body["thresholds"]}
    assert by_key == {
        "min_quality": (0.7, "score"),
        "max_error_rate": (0.1, "ratio"),
        "max_cost_per_request_usd": (0.05, "usd"),
        "max_quality_drop": (0.1, "score"),
        "min_requests": (20.0, "count"),
    }
    # Every threshold carries a human label for display.
    assert all(t["label"] for t in body["thresholds"])
