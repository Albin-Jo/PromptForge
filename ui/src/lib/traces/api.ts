import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { TraceDetail, TraceSummary } from "./types";

// The trace list pages (it's the fastest-growing table); this is the default page size the UI asks
// for. Mirrors the API's DEFAULT_TRACE_PAGE_SIZE — keep the two in step.
export const TRACE_PAGE_SIZE = 50;

export const traceKeys = {
  list: (prompt: string | undefined, version: number | undefined, offset: number) =>
    ["traces", prompt ?? null, version ?? null, offset] as const,
  detail: (id: string) => ["trace", id] as const,
};

export function listTraces(
  params: { prompt?: string; version?: number; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<TraceSummary[]> {
  const query = new URLSearchParams();
  if (params.prompt !== undefined) query.set("prompt", params.prompt);
  if (params.version !== undefined) query.set("version", String(params.version));
  query.set("limit", String(params.limit ?? TRACE_PAGE_SIZE));
  query.set("offset", String(params.offset ?? 0));
  return apiFetch<TraceSummary[]>(`/traces?${query.toString()}`, { signal });
}

export function getTrace(id: string, signal?: AbortSignal): Promise<TraceDetail> {
  return apiFetch<TraceDetail>(`/traces/${encodeURIComponent(id)}`, { signal });
}

/**
 * Server-state hook for a page of a prompt's traces (newest first). `version` scopes to one
 * version; `offset` pages through. Disabled until a prompt name is known. `placeholderData` keeps
 * the current page on screen while the next loads (no flash to a spinner on paging).
 */
export function useTraces(
  prompt: string | undefined,
  version: number | undefined,
  offset: number = 0,
) {
  return useQuery({
    queryKey: traceKeys.list(prompt, version, offset),
    queryFn: ({ signal }) =>
      listTraces({ prompt, version, limit: TRACE_PAGE_SIZE, offset }, signal),
    enabled: Boolean(prompt),
    placeholderData: (prev) => prev,
  });
}

/** Server-state hook for one trace in full (the drill-down). Disabled until an id is known. */
export function useTrace(id: string | undefined) {
  return useQuery({
    queryKey: traceKeys.detail(id ?? ""),
    queryFn: ({ signal }) => getTrace(id as string, signal),
    enabled: Boolean(id),
  });
}
