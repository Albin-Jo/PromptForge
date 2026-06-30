import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { AuditPage } from "./types";

export const AUDIT_PAGE_SIZE = 50;

export const auditKeys = {
  list: (offset: number) => ["audit-log", offset] as const,
};

export function listAuditEvents(
  params: { limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<AuditPage> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? AUDIT_PAGE_SIZE));
  query.set("offset", String(params.offset ?? 0));
  return apiFetch<AuditPage>(`/audit-log?${query.toString()}`, { signal });
}

/** Server-state hook for a page of audit events (newest first). */
export function useAuditEvents(offset: number = 0) {
  return useQuery({
    queryKey: auditKeys.list(offset),
    queryFn: ({ signal }) => listAuditEvents({ limit: AUDIT_PAGE_SIZE, offset }, signal),
    placeholderData: (prev) => prev,
  });
}
