// Mirrors the API's fleet-overview DTOs (api/.../schemas.py: OverviewResponse & PromptRollupDTO).
// The landing page's read surface: fleet totals + a gap-filled trend + a per-prompt rollup carrying
// "needs attention" rule keys. Reuses the metrics types for the block/bucket/window shapes.

import type { MetricsBlock, MetricsBucket, MetricsInterval } from "../metrics/types";

// The attention rule keys the API can emit (services/overview.py). Kept as a union so the UI maps
// each to its own label + badge style and a stray key is a type error, not a silent blank.
export type AttentionRule =
  | "high_error_rate"
  | "failing_or_missing_eval"
  | "unscanned_or_risky"
  | "no_recent_traffic";

// Mirrors PromptRollupDTO — one prompt's fleet row. cost_usd stays the exact decimal STRING.
export interface PromptRollup {
  name: string;
  latest_version: number | null;
  request_count: number;
  error_rate: number | null;
  p95_ms: number | null;
  cost_usd: string | null;
  quality: number | null;
  attention: AttentionRule[];
}

// Mirrors OverviewResponse — the whole landing page in one payload.
export interface FleetOverview {
  window: string;
  interval: MetricsInterval;
  since: string;
  totals: MetricsBlock;
  trend: MetricsBucket[];
  prompts: PromptRollup[];
}
