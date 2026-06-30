import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { QueueHealth } from "./types";

export const opsKeys = {
  // Process-wide health, not per-resource, so one static key.
  queues: ["ops", "queues"] as const,
};

/** Fetch Celery queue depth + worker liveness (admin-only endpoint). */
export function getQueueHealth(signal?: AbortSignal): Promise<QueueHealth> {
  return apiFetch<QueueHealth>("/admin/queues", { signal });
}

/** Server-state hook for queue/worker health; polls so the page tracks live backlog without reload. */
export function useQueueHealth() {
  return useQuery({
    queryKey: opsKeys.queues,
    queryFn: ({ signal }) => getQueueHealth(signal),
    // Health is live operational state — refetch on an interval so the backlog stays current.
    refetchInterval: 10_000,
  });
}
