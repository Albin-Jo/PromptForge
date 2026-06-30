import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api";
import { pollWhilePending } from "../polling";
import type { EvalRunAccepted, EvalRunSummary, EvalStatus, VersionEvalStatus } from "./types";

/** An eval is still in flight (so a poller should keep watching) while pending or running. */
export function isEvalRunning(status: EvalStatus): boolean {
  return status === "pending" || status === "running";
}

export const evalKeys = {
  detail: (name: string, versionNumber: number) => ["eval", name, versionNumber] as const,
  runs: (name: string, versionNumber: number) => ["eval-runs", name, versionNumber] as const,
};

export function getVersionEval(
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
): Promise<VersionEvalStatus> {
  return apiFetch<VersionEvalStatus>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/eval`,
    { signal },
  );
}

/** A version's eval runs, newest first — the audit history behind the latest status. */
export function listVersionEvals(
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
): Promise<EvalRunSummary[]> {
  return apiFetch<EvalRunSummary[]>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/evals`,
    { signal },
  );
}

/** Kick off an eval run for a version (202 → eval_run_id). The run executes async on the worker. */
export function triggerEval(name: string, versionNumber: number): Promise<EvalRunAccepted> {
  return apiFetch<EvalRunAccepted>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/evaluate`,
    { method: "POST" },
  );
}

/**
 * Trigger an eval, then invalidate that version's eval status so the panel re-reads (and starts
 * polling) the now-pending run.
 */
export function useTriggerEval(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionNumber: number) => triggerEval(name, versionNumber),
    onSuccess: (_data, versionNumber) => {
      void queryClient.invalidateQueries({ queryKey: evalKeys.detail(name, versionNumber) });
    },
  });
}

/**
 * Server-state hook for one version's eval status + score summary. Disabled until both args.
 * Pass `{ poll: true }` to watch a triggered run to completion (stops at completed/failed).
 */
export function useVersionEval(
  name: string | undefined,
  versionNumber: number | undefined,
  options: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: evalKeys.detail(name ?? "", versionNumber ?? -1),
    queryFn: ({ signal }) => getVersionEval(name as string, versionNumber as number, signal),
    enabled: Boolean(name) && versionNumber !== undefined,
    refetchInterval: options.poll
      ? pollWhilePending<VersionEvalStatus>((d) => isEvalRunning(d.status))
      : undefined,
  });
}

/**
 * Server-state hook for a version's eval run history (newest first). Disabled until both args.
 * Pass `{ poll: true }` to keep the list fresh while any run in it is still in flight.
 */
export function useVersionEvals(
  name: string | undefined,
  versionNumber: number | undefined,
  options: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: evalKeys.runs(name ?? "", versionNumber ?? -1),
    queryFn: ({ signal }) => listVersionEvals(name as string, versionNumber as number, signal),
    enabled: Boolean(name) && versionNumber !== undefined,
    refetchInterval: options.poll
      ? pollWhilePending<EvalRunSummary[]>((runs) => runs.some((r) => isEvalRunning(r.status)))
      : undefined,
  });
}
