// Pure transforms from the API's time-series read surface (ADR 0022) into chart-ready rows, plus the
// axis/tooltip formatters. Kept framework-free and side-effect-free so the data-shaping — especially
// the gap-filled empty/zero buckets — is unit-testable without rendering a chart.

import type { ChartDatum } from "@/components/ui/chart";
import type { MetricsBucket, MetricsInterval, PromptTimeseries } from "./types";

// One charting row. `bucket` is the x value (the bucket's ISO start). Counts are real numbers (0 for
// an empty bucket); rates/latency/quality stay null on empties so a line *breaks* over the gap
// rather than diving to 0. `cost` is `Number(cost_usd)` — used ONLY to position the point on a cost
// axis; the exact decimal string stays the source of truth for any displayed figure.
export interface TrendDatum extends ChartDatum {
  bucket: string;
  requests: number;
  errorRate: number | null;
  p50: number | null;
  p95: number | null;
  p99: number | null;
  cost: number | null;
  quality: number | null;
}

function bucketCost(cost: string | null): number | null {
  if (cost === null) return null;
  const n = Number(cost);
  return Number.isNaN(n) ? null : n;
}

/** Map gap-filled buckets into trend rows, preserving nulls (no faked zeros). */
export function bucketsToTrend(buckets: MetricsBucket[]): TrendDatum[] {
  return buckets.map((b: MetricsBucket) => ({
    bucket: b.bucket_start,
    requests: b.request_count,
    errorRate: b.error_rate,
    p50: b.p50_ms,
    p95: b.p95_ms,
    p99: b.p99_ms,
    cost: bucketCost(b.cost_usd),
    quality: b.quality,
  }));
}

/** Map a prompt's time-series into trend rows (delegates to {@link bucketsToTrend}). */
export function toTrendData(series: PromptTimeseries): TrendDatum[] {
  return bucketsToTrend(series.buckets);
}

/** True when every bucket is empty — lets a panel show an "no traffic" state instead of a flat line. */
export function isEmptySeries(series: PromptTimeseries): boolean {
  return series.buckets.every((b) => b.request_count === 0);
}

/** Total requests across the window (handy for a header stat without re-fetching the aggregate). */
export function totalRequests(series: PromptTimeseries): number {
  return series.buckets.reduce((sum, b) => sum + b.request_count, 0);
}

// --- axis / tooltip formatters -------------------------------------------------------------------
// Hourly buckets read as a time of day ("14:00"); daily as a short date ("Jun 23"). Invalid input
// returns the raw value rather than throwing, so a malformed bucket never blanks the whole axis.

function parse(iso: unknown): Date | null {
  if (typeof iso !== "string") return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatBucketTick(iso: unknown, interval: MetricsInterval): string {
  const d = parse(iso);
  if (!d) return typeof iso === "string" ? iso : "";
  return interval === "hour"
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatBucketLabel(iso: unknown, interval: MetricsInterval): string {
  const d = parse(iso);
  if (!d) return typeof iso === "string" ? iso : "";
  return interval === "hour"
    ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
