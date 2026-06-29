import { describe, expect, it } from "vitest";

import {
  formatBucketLabel,
  formatBucketTick,
  isEmptySeries,
  toTrendData,
  totalRequests,
} from "./timeseries";
import type { MetricsBucket, PromptTimeseries } from "./types";

function bucket(partial: Partial<MetricsBucket> & { bucket_start: string }): MetricsBucket {
  return {
    request_count: 0,
    error_rate: null,
    p50_ms: null,
    p95_ms: null,
    p99_ms: null,
    cost_usd: null,
    quality: null,
    ...partial,
  };
}

function series(buckets: MetricsBucket[], interval: "hour" | "day" = "day"): PromptTimeseries {
  return {
    name: "p",
    prompt_id: "id",
    window: "7d",
    interval,
    since: "2026-06-17T00:00:00Z",
    version: null,
    buckets,
  };
}

describe("toTrendData", () => {
  it("maps a populated bucket field-for-field, with cost read as a plotting number", () => {
    const [row] = toTrendData(
      series([
        bucket({
          bucket_start: "2026-06-23T00:00:00Z",
          request_count: 12,
          error_rate: 0.25,
          p50_ms: 120,
          p95_ms: 290,
          p99_ms: 450,
          cost_usd: "0.003000",
          quality: 0.8,
        }),
      ]),
    );
    expect(row).toEqual({
      bucket: "2026-06-23T00:00:00Z",
      requests: 12,
      errorRate: 0.25,
      p50: 120,
      p95: 290,
      p99: 450,
      cost: 0.003,
      quality: 0.8,
    });
  });

  it("preserves a gap-filled empty bucket as zero count with null rate/latency/cost/quality", () => {
    // The whole point of server-side gap-fill: the empty bucket is *present* and must stay null on
    // the rate/latency/cost/quality fields so the chart breaks the line instead of dipping to 0.
    const [row] = toTrendData(series([bucket({ bucket_start: "2026-06-22T00:00:00Z" })]));
    expect(row.requests).toBe(0);
    expect(row.errorRate).toBeNull();
    expect(row.p50).toBeNull();
    expect(row.p95).toBeNull();
    expect(row.p99).toBeNull();
    expect(row.cost).toBeNull();
    expect(row.quality).toBeNull();
  });

  it("keeps every bucket in order (no holes dropped)", () => {
    const rows = toTrendData(
      series([
        bucket({ bucket_start: "2026-06-22T00:00:00Z", request_count: 3 }),
        bucket({ bucket_start: "2026-06-23T00:00:00Z" }), // empty middle
        bucket({ bucket_start: "2026-06-24T00:00:00Z", request_count: 5 }),
      ]),
    );
    expect(rows.map((r) => r.bucket)).toEqual([
      "2026-06-22T00:00:00Z",
      "2026-06-23T00:00:00Z",
      "2026-06-24T00:00:00Z",
    ]);
    expect(rows.map((r) => r.requests)).toEqual([3, 0, 5]);
  });

  it("treats a malformed cost string as absent rather than NaN", () => {
    const [row] = toTrendData(
      series([bucket({ bucket_start: "2026-06-23T00:00:00Z", cost_usd: "oops" })]),
    );
    expect(row.cost).toBeNull();
  });
});

describe("isEmptySeries / totalRequests", () => {
  it("isEmptySeries is true only when no bucket had traffic", () => {
    expect(isEmptySeries(series([bucket({ bucket_start: "a" }), bucket({ bucket_start: "b" })]))).toBe(
      true,
    );
    expect(
      isEmptySeries(series([bucket({ bucket_start: "a", request_count: 1 })])),
    ).toBe(false);
  });

  it("totalRequests sums counts across buckets", () => {
    expect(
      totalRequests(
        series([
          bucket({ bucket_start: "a", request_count: 3 }),
          bucket({ bucket_start: "b" }),
          bucket({ bucket_start: "c", request_count: 5 }),
        ]),
      ),
    ).toBe(8);
  });
});

describe("formatters", () => {
  it("formats daily ticks as a short date and hourly as a time", () => {
    // Use UTC-noon to dodge any local-midnight date rollover in the daily case.
    expect(formatBucketTick("2026-06-23T12:00:00Z", "day")).toMatch(/Jun/);
    expect(formatBucketTick("2026-06-23T12:00:00Z", "hour")).toMatch(/\d{1,2}:\d{2}/);
  });

  it("falls back to the raw value on an unparseable date instead of throwing", () => {
    expect(formatBucketTick("not-a-date", "day")).toBe("not-a-date");
    expect(formatBucketLabel("not-a-date", "hour")).toBe("not-a-date");
  });
});
