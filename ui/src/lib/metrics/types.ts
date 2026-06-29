// Mirrors the API's metrics DTOs (api/.../schemas.py: PromptMetricsResponse & friends).
//
// The observability data layer the Sprint 16 dashboards render: aggregated latency / error /
// cost / quality for a prompt over a window. There is no raw-trace list endpoint — these
// aggregates are the read surface (see metrics.py docstring).

// The windows the endpoint accepts (must match the API's MetricsWindow Literal).
export type MetricsWindow = "24h" | "7d" | "30d";

// Mirrors LatencyPercentilesDTO. Each value is null when no latency was recorded.
export interface LatencyPercentiles {
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

// Mirrors MetricsBlockDTO — an aggregate over a set of executions.
// total_cost_usd is a STRING (e.g. "0.000450"), not a number: money keeps its exact decimal
// value across the wire. Never parseFloat it for arithmetic — display it as-is / format the string.
export interface MetricsBlock {
  request_count: number;
  error_count: number;
  error_rate: number | null;
  latency: LatencyPercentiles;
  total_cost_usd: string | null;
}

// Mirrors VersionMetricsDTO — one version's block plus its latest eval quality (mean in [0,1]).
export interface VersionMetrics {
  version_number: number;
  prompt_version_id: string;
  quality: number | null;
  metrics: MetricsBlock;
}

// Mirrors SourceCostDTO — spend attributed to one feature/source.
export interface SourceCost {
  source: string | null;
  cost_usd: string | null;
}

// Mirrors PromptMetricsResponse — a prompt's observability view over a window.
export interface PromptMetrics {
  name: string;
  prompt_id: string;
  window: string;
  since: string;
  overall: MetricsBlock;
  by_version: VersionMetrics[];
  by_source: SourceCost[];
}

// --- time-series read surface (ADR 0022) ---------------------------------------------------------
// The bucket sizes the timeseries endpoint accepts (must match the API's MetricsInterval Literal).
export type MetricsInterval = "hour" | "day";

// Mirrors MetricsBucketDTO — one time bucket. Empty buckets are *present* (gap-filled): request_count
// is a real 0 while error_rate / p95_ms / cost_usd / quality are null when the bucket had no traffic
// or no eval. cost_usd stays the exact decimal STRING — never parseFloat it for arithmetic.
export interface MetricsBucket {
  bucket_start: string;
  request_count: number;
  error_rate: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  cost_usd: string | null;
  quality: number | null;
}

// Mirrors PromptTimeseriesResponse — a prompt's metrics bucketed over time. `interval` echoes the
// bucket size used (defaults from the window when unset); `since` the inclusive window cutoff.
export interface PromptTimeseries {
  name: string;
  prompt_id: string;
  window: string;
  interval: MetricsInterval;
  since: string;
  // The version the series was scoped to, or null for the whole prompt (every version combined).
  version: number | null;
  buckets: MetricsBucket[];
}
