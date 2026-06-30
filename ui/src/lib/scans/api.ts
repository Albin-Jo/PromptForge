import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api";
import { pollWhilePending } from "../polling";
import type { ScanAccepted, ScanRunSummary, ScanStatus, VersionScanStatus } from "./types";

/** A scan is still in flight (so a poller should keep watching) while pending or running. */
export function isScanRunning(status: ScanStatus): boolean {
  return status === "pending" || status === "running";
}

export const scanKeys = {
  detail: (name: string, versionNumber: number) => ["scan", name, versionNumber] as const,
  runs: (name: string, versionNumber: number) => ["scan-runs", name, versionNumber] as const,
};

export function getVersionScan(
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
): Promise<VersionScanStatus> {
  return apiFetch<VersionScanStatus>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/scan`,
    { signal },
  );
}

/** A version's scans, newest first — the audit history behind the latest status. */
export function listVersionScans(
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
): Promise<ScanRunSummary[]> {
  return apiFetch<ScanRunSummary[]>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/scans`,
    { signal },
  );
}

/** Kick off a security scan for a version (202 → security_scan_id). Runs async on the worker. */
export function triggerScan(name: string, versionNumber: number): Promise<ScanAccepted> {
  return apiFetch<ScanAccepted>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/scan`,
    { method: "POST" },
  );
}

/**
 * Trigger a scan, then invalidate that version's scan status so the view re-reads (and starts
 * polling) the now-pending scan.
 */
export function useTriggerScan(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionNumber: number) => triggerScan(name, versionNumber),
    onSuccess: (_data, versionNumber) => {
      void queryClient.invalidateQueries({ queryKey: scanKeys.detail(name, versionNumber) });
    },
  });
}

/**
 * Server-state hook for one version's scan status + findings. Disabled until both args.
 * Pass `{ poll: true }` to watch a triggered scan to completion (stops at completed/failed).
 */
export function useVersionScan(
  name: string | undefined,
  versionNumber: number | undefined,
  options: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: scanKeys.detail(name ?? "", versionNumber ?? -1),
    queryFn: ({ signal }) => getVersionScan(name as string, versionNumber as number, signal),
    enabled: Boolean(name) && versionNumber !== undefined,
    refetchInterval: options.poll
      ? pollWhilePending<VersionScanStatus>((d) => isScanRunning(d.status))
      : undefined,
  });
}

/**
 * Server-state hook for a version's scan run history (newest first). Disabled until both args.
 * Pass `{ poll: true }` to keep the list fresh while any scan in it is still in flight.
 */
export function useVersionScans(
  name: string | undefined,
  versionNumber: number | undefined,
  options: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: scanKeys.runs(name ?? "", versionNumber ?? -1),
    queryFn: ({ signal }) => listVersionScans(name as string, versionNumber as number, signal),
    enabled: Boolean(name) && versionNumber !== undefined,
    refetchInterval: options.poll
      ? pollWhilePending<ScanRunSummary[]>((scans) => scans.some((s) => isScanRunning(s.status)))
      : undefined,
  });
}
