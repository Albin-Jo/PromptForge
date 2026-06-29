import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../api";
import { METRICS_REFETCH_MS } from "../metrics/api";
import type { MetricsWindow } from "../metrics/types";
import type { FleetOverview } from "./types";

export const overviewKeys = {
  // One cache entry per window, mirroring the metrics keys.
  detail: (window: MetricsWindow) => ["overview", window] as const,
};

export function getOverview(window: MetricsWindow, signal?: AbortSignal): Promise<FleetOverview> {
  return apiFetch<FleetOverview>(`/overview?window=${window}`, { signal });
}

/** Server-state hook for the fleet overview over a window. */
export function useOverview(window: MetricsWindow) {
  return useQuery({
    queryKey: overviewKeys.detail(window),
    queryFn: ({ signal }) => getOverview(window, signal),
    refetchInterval: METRICS_REFETCH_MS,
  });
}
