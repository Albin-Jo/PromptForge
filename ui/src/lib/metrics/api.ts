import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { MetricsInterval, MetricsWindow, PromptMetrics, PromptTimeseries } from "./types";

export const metricsKeys = {
  // Each window is cached separately so the selector can switch without a refetch flicker.
  detail: (name: string, window: MetricsWindow) => ["metrics", name, window] as const,
  // The time-series read surface keys on the bucket size and version too (default/whole-prompt).
  timeseries: (
    name: string,
    window: MetricsWindow,
    interval: MetricsInterval | undefined,
    version: number | undefined,
  ) => ["metrics", "timeseries", name, window, interval ?? "default", version ?? "all"] as const,
};

export function getPromptMetrics(
  name: string,
  window: MetricsWindow,
  signal?: AbortSignal,
): Promise<PromptMetrics> {
  return apiFetch<PromptMetrics>(
    `/prompts/${encodeURIComponent(name)}/metrics?window=${window}`,
    { signal },
  );
}

// Observability data goes stale on its own (new executions land continuously), so the aggregate
// re-fetches in the background while a dashboard is open. The freshness indicator surfaces when.
export const METRICS_REFETCH_MS = 30_000;

/** Server-state hook for a prompt's observability metrics over a window. Disabled until a name. */
export function usePromptMetrics(name: string | undefined, window: MetricsWindow) {
  return useQuery({
    queryKey: metricsKeys.detail(name ?? "", window),
    queryFn: ({ signal }) => getPromptMetrics(name as string, window, signal),
    enabled: Boolean(name),
    refetchInterval: METRICS_REFETCH_MS,
  });
}

export function getPromptTimeseries(
  name: string,
  window: MetricsWindow,
  interval: MetricsInterval | undefined,
  version: number | undefined,
  signal?: AbortSignal,
): Promise<PromptTimeseries> {
  const q = new URLSearchParams({ window });
  if (interval) q.set("interval", interval);
  if (version !== undefined) q.set("version", String(version));
  return apiFetch<PromptTimeseries>(
    `/prompts/${encodeURIComponent(name)}/metrics/timeseries?${q.toString()}`,
    { signal },
  );
}

/**
 * Server-state hook for a prompt's metrics bucketed over time (trend charts). `version` scopes the
 * series to one version (per-version sparklines); omit for the whole prompt. Disabled until a name.
 */
export function usePromptTimeseries(
  name: string | undefined,
  window: MetricsWindow,
  interval?: MetricsInterval,
  version?: number,
) {
  return useQuery({
    queryKey: metricsKeys.timeseries(name ?? "", window, interval, version),
    queryFn: ({ signal }) => getPromptTimeseries(name as string, window, interval, version, signal),
    enabled: Boolean(name),
  });
}
