"""Aggregation read-model: the Sprint 9 DoD "aggregation-query assertion".

Against a real throwaway Postgres, seed a window of traces with *known* latency/cost/status across
versions and sources (+ an eval run for quality), then assert the numbers the metrics endpoint
computes: latency percentiles (the ordered-set aggregate, interpolated), error rate, spend, the
per-version attribution, per-feature cost split, quality, and the window cutoff.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from promptforge_api.db.eval_models import EvalRun
from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.trace_models import Trace
from promptforge_api.repositories.metrics import MetricsRepository
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.services.metrics import MetricsService


def _trace(
    *,
    prompt_id: uuid.UUID,
    version_id: uuid.UUID | None,
    latency: int,
    status: str = "ok",
    source: str = "sdk",
    cost: str = "0.001",
    created_at: datetime | None = None,
) -> Trace:
    return Trace(
        prompt_id=prompt_id,
        prompt_version_id=version_id,
        model="openai/gpt-4o-mini",
        status=status,
        source=source,
        latency_ms=latency,
        cost_usd=Decimal(cost),
        created_at=created_at or datetime.now(UTC),
    )


@pytest.fixture
def seeded(db_session: Session) -> Prompt:
    """A prompt with two versions and a known set of traces + one completed eval run on v1."""
    prompt = Prompt(name="obs")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    prompt.versions.append(PromptVersion(version_number=2, content="b"))
    db_session.add(prompt)
    db_session.flush()
    v1, v2 = prompt.versions[0].id, prompt.versions[1].id

    db_session.add_all(
        [
            # v1: latencies 100/200/300/400, the last one an error — all source "sdk".
            _trace(prompt_id=prompt.id, version_id=v1, latency=100),
            _trace(prompt_id=prompt.id, version_id=v1, latency=200),
            _trace(prompt_id=prompt.id, version_id=v1, latency=300),
            _trace(prompt_id=prompt.id, version_id=v1, latency=400, status="error"),
            # v2: a single ok trace.
            _trace(prompt_id=prompt.id, version_id=v2, latency=150),
            # A version-less call: counts in `overall` and `by_source`, never in `by_version`.
            _trace(
                prompt_id=prompt.id, version_id=None, latency=500, source="playground", cost="0.002"
            ),
        ]
    )

    # Two completed eval runs on v1; the later one must win the quality lookup.
    db_session.add_all(
        [
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.2}}},
                completed_at=datetime.now(UTC) - timedelta(days=1),
            ),
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.8}, "ragas": {"mean_value": 0.6}}},
                completed_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.flush()
    return prompt


def _service(db_session: Session) -> MetricsService:
    return MetricsService(PromptRepository(db_session), MetricsRepository(db_session))


def test_overall_aggregates_every_trace_in_the_window(seeded: Prompt, db_session: Session) -> None:
    overall = _service(db_session).prompt_metrics(name="obs", window="7d").overall

    assert overall.request_count == 6  # includes the version-less call
    assert overall.error_count == 1
    assert overall.error_rate == pytest.approx(1 / 6)
    assert overall.total_cost_usd == Decimal("0.007")  # 4x0.001 + 0.001 + 0.002
    # percentile_cont over sorted [100,150,200,300,400,500]: interpolated between rows.
    assert overall.latency.p50_ms == pytest.approx(250.0)
    assert overall.latency.p95_ms == pytest.approx(475.0)
    assert overall.latency.p99_ms == pytest.approx(495.0)


def test_by_version_attributes_and_excludes_versionless(
    seeded: Prompt, db_session: Session
) -> None:
    by_version = _service(db_session).prompt_metrics(name="obs", window="7d").by_version

    assert [v.version_number for v in by_version] == [1, 2]  # ordered, version-less excluded

    v1 = by_version[0]
    assert v1.metrics.request_count == 4
    assert v1.metrics.error_rate == pytest.approx(0.25)
    assert v1.metrics.total_cost_usd == Decimal("0.004")
    # percentile_cont over [100,200,300,400]
    assert v1.metrics.latency.p50_ms == pytest.approx(250.0)
    assert v1.metrics.latency.p95_ms == pytest.approx(385.0)

    v2 = by_version[1]
    assert v2.metrics.request_count == 1
    assert v2.metrics.latency.p50_ms == pytest.approx(150.0)  # single value → all percentiles equal


def test_quality_uses_latest_completed_eval_per_version(
    seeded: Prompt, db_session: Session
) -> None:
    by_version = {
        v.version_number: v
        for v in _service(db_session).prompt_metrics(name="obs", window="7d").by_version
    }
    # v1: mean of the *latest* run's scorers = (0.8 + 0.6)/2 = 0.7 (not the older 0.2 run).
    assert by_version[1].quality == pytest.approx(0.7)
    # v2: never evaluated → quality absent, not 0.
    assert by_version[2].quality is None


def test_quality_ignores_completed_run_without_timestamp(db_session: Session) -> None:
    """A completed run with a NULL completed_at must not win the 'latest' lookup.

    Guards the DISTINCT ON … ORDER BY completed_at DESC: Postgres sorts NULLs first under DESC, so
    without the completed_at IS NOT NULL filter the timestamp-less run would shadow the real one.
    """
    prompt = Prompt(name="timestamps")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()
    v1 = prompt.versions[0].id

    db_session.add(_trace(prompt_id=prompt.id, version_id=v1, latency=100))  # so v1 appears
    db_session.add_all(
        [
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.6}}},
                completed_at=datetime.now(UTC),  # the real latest
            ),
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.99}}},
                completed_at=None,  # malformed — must be ignored, not chosen
            ),
        ]
    )
    db_session.flush()

    by_version = _service(db_session).prompt_metrics(name="timestamps", window="7d").by_version
    assert by_version[0].quality == pytest.approx(0.6)  # not 0.99


def test_cost_attributed_per_source(seeded: Prompt, db_session: Session) -> None:
    by_source = _service(db_session).prompt_metrics(name="obs", window="7d").by_source

    assert [(s.source, s.cost_usd) for s in by_source] == [
        ("playground", Decimal("0.002")),
        ("sdk", Decimal("0.005")),  # five sdk traces x 0.001
    ]


def test_window_excludes_older_traces(db_session: Session) -> None:
    prompt = Prompt(name="windowed")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()
    v1 = prompt.versions[0].id

    db_session.add_all(
        [
            _trace(prompt_id=prompt.id, version_id=v1, latency=100),  # now
            _trace(
                prompt_id=prompt.id,
                version_id=v1,
                latency=100,
                created_at=datetime.now(UTC) - timedelta(days=10),  # outside 7d, inside 30d
            ),
        ]
    )
    db_session.flush()

    svc = _service(db_session)
    assert svc.prompt_metrics(name="windowed", window="7d").overall.request_count == 1
    assert svc.prompt_metrics(name="windowed", window="30d").overall.request_count == 2


def test_empty_prompt_reports_nulls_not_zeros(db_session: Session) -> None:
    prompt = Prompt(name="quiet")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()

    overall = _service(db_session).prompt_metrics(name="quiet", window="7d").overall
    assert overall.request_count == 0
    assert overall.error_rate is None  # no faked 0 over an empty window
    assert overall.latency.p50_ms is None
    assert overall.total_cost_usd is None


# --------------------------------------------------------------------- HTTP surface
def test_metrics_endpoint_shape_and_string_money(seeded: Prompt, client: TestClient) -> None:
    body = client.get("/prompts/obs/metrics", params={"window": "7d"}).json()

    assert body["name"] == "obs"
    assert body["window"] == "7d"
    assert body["overall"]["request_count"] == 6
    # money crosses the wire as an exact string, not a lossy float.
    assert body["overall"]["total_cost_usd"] == "0.007000"
    assert body["by_version"][0]["version_number"] == 1
    assert body["by_version"][0]["quality"] == pytest.approx(0.7)


def test_metrics_endpoint_404_for_unknown_prompt(client: TestClient) -> None:
    assert client.get("/prompts/nope/metrics").status_code == 404


def test_metrics_endpoint_422_for_bad_window(seeded: Prompt, client: TestClient) -> None:
    assert client.get("/prompts/obs/metrics", params={"window": "1y"}).status_code == 422


# --------------------------------------------------------------------- time-series read-model
@pytest.fixture
def bucketed(db_session: Session) -> Prompt:
    """A prompt whose traffic lands in *known* daily buckets, with a deliberate empty day between.

    Today: three traces (one error). Two days ago: one trace. One day ago: nothing — the gap-fill
    case. Plus two completed eval runs, today (0.8) and two days ago (0.4), to exercise quality.
    """
    prompt = Prompt(name="series")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    db_session.add(prompt)
    db_session.flush()
    v1 = prompt.versions[0].id

    now = datetime.now(UTC)
    db_session.add_all(
        [
            _trace(prompt_id=prompt.id, version_id=v1, latency=100, created_at=now),
            _trace(prompt_id=prompt.id, version_id=v1, latency=200, created_at=now),
            _trace(prompt_id=prompt.id, version_id=v1, latency=300, status="error", created_at=now),
            # one day ago: intentionally empty (gap-fill must still emit this bucket)
            _trace(
                prompt_id=prompt.id, version_id=v1, latency=500, created_at=now - timedelta(days=2)
            ),
        ]
    )
    db_session.add_all(
        [
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.8}}},
                completed_at=now,
            ),
            EvalRun(
                prompt_version_id=v1,
                scorer_config=[],
                status="completed",
                summary={"scorers": {"judge": {"mean_value": 0.4}}},
                completed_at=now - timedelta(days=2),
            ),
        ]
    )
    db_session.flush()
    return prompt


def _by_day(buckets: list) -> dict:  # type: ignore[type-arg]
    """Index daily buckets by their UTC date for assertion."""
    return {b.bucket_start.date(): b for b in buckets}


def test_timeseries_buckets_gap_fill_and_values(bucketed: Prompt, db_session: Session) -> None:
    series = _service(db_session).prompt_timeseries(name="series", window="7d")
    assert series.interval == "day"  # defaulted from the window

    # The spine is complete and ordered: every day from the truncated `since` to today is present,
    # contiguous (one-day steps), so a chart can trust there are no holes.
    starts = [b.bucket_start for b in series.buckets]
    assert starts == sorted(starts)
    assert all((b - a) == timedelta(days=1) for a, b in zip(starts, starts[1:], strict=False))

    now = datetime.now(UTC)
    days = _by_day(series.buckets)
    today, gap, two_ago = (
        (now).date(),
        (now - timedelta(days=1)).date(),
        (now - timedelta(days=2)).date(),
    )

    # Today: three traces, one error; p95 interpolates over [100,200,300].
    assert days[today].request_count == 3
    assert days[today].error_rate == pytest.approx(1 / 3)
    assert days[today].p95_ms == pytest.approx(290.0)
    assert days[today].cost_usd == Decimal("0.003")
    assert days[today].quality == pytest.approx(0.8)

    # The empty day is *present* (gap-filled) with a real 0 count and honest nulls, not absent.
    assert gap in days
    assert days[gap].request_count == 0
    assert days[gap].error_rate is None
    assert days[gap].p95_ms is None
    assert days[gap].cost_usd is None
    assert days[gap].quality is None

    # Two days ago: the single trace and its eval quality.
    assert days[two_ago].request_count == 1
    assert days[two_ago].quality == pytest.approx(0.4)


def test_timeseries_interval_override_uses_hourly_buckets(
    bucketed: Prompt, db_session: Session
) -> None:
    series = _service(db_session).prompt_timeseries(name="series", window="24h", interval="hour")
    assert series.interval == "hour"
    # 24h of hourly buckets ≈ 25 boundaries; today's three traces all land in the latest bucket.
    assert series.buckets[-1].request_count == 3
    # the 2-days-ago trace is outside the 24h window
    assert sum(b.request_count for b in series.buckets) == 3


def test_timeseries_endpoint_shape_and_string_money(bucketed: Prompt, client: TestClient) -> None:
    body = client.get("/prompts/series/metrics/timeseries", params={"window": "7d"}).json()

    assert body["name"] == "series"
    assert body["interval"] == "day"
    assert isinstance(body["buckets"], list) and len(body["buckets"]) >= 7
    populated = [b for b in body["buckets"] if b["request_count"] == 3][0]
    assert populated["cost_usd"] == "0.003000"  # exact string, not a float
    assert populated["quality"] == pytest.approx(0.8)


def test_timeseries_scopes_to_one_version(db_session: Session) -> None:
    """version=N filters the trace spine to that version's traffic (the per-version sparklines)."""
    prompt = Prompt(name="versioned")
    prompt.versions.append(PromptVersion(version_number=1, content="a"))
    prompt.versions.append(PromptVersion(version_number=2, content="b"))
    db_session.add(prompt)
    db_session.flush()
    v1, v2 = prompt.versions[0].id, prompt.versions[1].id

    now = datetime.now(UTC)
    db_session.add_all(
        [_trace(prompt_id=prompt.id, version_id=v1, latency=100, created_at=now) for _ in range(3)]
        + [
            _trace(prompt_id=prompt.id, version_id=v2, latency=100, created_at=now)
            for _ in range(7)
        ]
    )
    db_session.flush()

    svc = _service(db_session)
    whole = svc.prompt_timeseries(name="versioned", window="7d")
    just_v1 = svc.prompt_timeseries(name="versioned", window="7d", version=1)
    just_v2 = svc.prompt_timeseries(name="versioned", window="7d", version=2)

    assert whole.version is None
    assert sum(b.request_count for b in whole.buckets) == 10
    assert just_v1.version == 1
    assert sum(b.request_count for b in just_v1.buckets) == 3
    assert just_v2.version == 2
    assert sum(b.request_count for b in just_v2.buckets) == 7
    # Still gap-filled — the spine is the full window, not just days with this version's traffic.
    assert len(just_v1.buckets) == len(whole.buckets)


def test_timeseries_endpoint_404_for_unknown_prompt(client: TestClient) -> None:
    assert client.get("/prompts/nope/metrics/timeseries").status_code == 404


def test_timeseries_endpoint_404_for_unknown_version(bucketed: Prompt, client: TestClient) -> None:
    resp = client.get("/prompts/series/metrics/timeseries", params={"version": 999})
    assert resp.status_code == 404


def test_timeseries_endpoint_422_for_bad_interval(bucketed: Prompt, client: TestClient) -> None:
    resp = client.get("/prompts/series/metrics/timeseries", params={"interval": "week"})
    assert resp.status_code == 422
