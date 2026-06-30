import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { ModelsResponse } from "./types";

export const gatewayKeys = {
  // The configured model list is process-wide config, not per-resource, so one static key.
  models: ["gateway", "models"] as const,
};

/** Fetch the model identifiers the gateway exposes for the playground picker. */
export function listModels(signal?: AbortSignal): Promise<ModelsResponse> {
  return apiFetch<ModelsResponse>("/models", { signal });
}

/** Server-state hook for the configured model list. Empty list = unconfigured (free-text UI). */
export function useModels() {
  return useQuery({
    queryKey: gatewayKeys.models,
    queryFn: ({ signal }) => listModels(signal),
  });
}
