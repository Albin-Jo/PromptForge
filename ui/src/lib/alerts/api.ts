import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { MetricsWindow } from "../metrics/types";
import type { AlertPolicy, PromptAlerts } from "./types";

export const alertKeys = {
  // One window's alerts for one prompt. Windowed separately so switching window doesn't evict.
  detail: (name: string, window: MetricsWindow) => ["alerts", name, window] as const,
  // The configured thresholds are process-wide config, not per-prompt, so one static key.
  policy: ["alerts", "policy"] as const,
};

export function getPromptAlerts(
  name: string,
  window: MetricsWindow,
  signal?: AbortSignal,
): Promise<PromptAlerts> {
  return apiFetch<PromptAlerts>(`/prompts/${encodeURIComponent(name)}/alerts?window=${window}`, {
    signal,
  });
}

/** Server-state hook for the drift/regression alerts firing on a prompt. Disabled until a name. */
export function usePromptAlerts(name: string | undefined, window: MetricsWindow) {
  return useQuery({
    queryKey: alertKeys.detail(name ?? "", window),
    queryFn: ({ signal }) => getPromptAlerts(name as string, window, signal),
    enabled: Boolean(name),
  });
}

/** Fetch the configured drift-alert thresholds (global config, not per-prompt; ADR 0026). */
export function getAlertPolicy(signal?: AbortSignal): Promise<AlertPolicy> {
  return apiFetch<AlertPolicy>("/alert-policy", { signal });
}

/** Server-state hook for the active alert thresholds. Supplementary, so callers degrade if absent. */
export function useAlertPolicy() {
  return useQuery({
    queryKey: alertKeys.policy,
    queryFn: ({ signal }) => getAlertPolicy(signal),
  });
}
