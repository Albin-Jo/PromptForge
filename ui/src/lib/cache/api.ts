import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { CacheStats } from "./types";

export const cacheKeys = {
  detail: (name: string) => ["cache", name] as const,
};

/** Fetch a prompt's render-cache hit-rate (admin-only endpoint). */
export function getCacheStats(name: string, signal?: AbortSignal): Promise<CacheStats> {
  return apiFetch<CacheStats>(`/prompts/${encodeURIComponent(name)}/cache`, { signal });
}

/**
 * Server-state hook for a prompt's render-cache hit-rate. The endpoint is admin-only, so callers
 * pass `enabled` (their admin check) to avoid even firing the request for a non-admin.
 */
export function useCacheStats(name: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: cacheKeys.detail(name ?? ""),
    queryFn: ({ signal }) => getCacheStats(name as string, signal),
    enabled: Boolean(name) && enabled,
  });
}
