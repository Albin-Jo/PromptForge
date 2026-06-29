import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type { DatasetCreate, DatasetDetail, DatasetSummary, DatasetUpdate } from "./types";

export const datasetKeys = {
  all: ["datasets"] as const,
  detail: (name: string) => ["dataset", name] as const,
};

export function listDatasets(signal?: AbortSignal): Promise<DatasetSummary[]> {
  return apiFetch<DatasetSummary[]>("/datasets", { signal });
}

export function getDataset(name: string, signal?: AbortSignal): Promise<DatasetDetail> {
  return apiFetch<DatasetDetail>(`/datasets/${encodeURIComponent(name)}`, { signal });
}

export function createDataset(body: DatasetCreate): Promise<DatasetSummary> {
  return apiFetch<DatasetSummary>("/datasets", { method: "POST", body });
}

/** Replace a golden set's description + cases wholesale (PUT — ADR 0024). */
export function updateDataset(name: string, body: DatasetUpdate): Promise<DatasetSummary> {
  return apiFetch<DatasetSummary>(`/datasets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body,
  });
}

/**
 * Delete a golden set. Can 409 (`DatasetInUseError`) when a prompt still gates on it — we let
 * apiFetch throw `ApiError` and the page reads `err.body.detail` (which names the prompts), the
 * same "409-is-state, not error" handling as the promote flow (Sprint 16e / ADR 0023).
 */
export function deleteDataset(name: string): Promise<void> {
  return apiFetch<void>(`/datasets/${encodeURIComponent(name)}`, { method: "DELETE" });
}

/** Server-state hook for the dataset list. */
export function useDatasets() {
  return useQuery({
    queryKey: datasetKeys.all,
    queryFn: ({ signal }) => listDatasets(signal),
  });
}

/** Server-state hook for one golden set with its cases. Disabled until a name is given. */
export function useDataset(name: string | undefined) {
  return useQuery({
    queryKey: datasetKeys.detail(name ?? ""),
    queryFn: ({ signal }) => getDataset(name as string, signal),
    enabled: Boolean(name),
  });
}

/** Create a golden set; refreshes the list on success. */
export function useCreateDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createDataset,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: datasetKeys.all });
    },
  });
}

/** Replace a golden set's cases; refreshes the list + that set's detail. */
export function useUpdateDataset(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DatasetUpdate) => updateDataset(name, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: datasetKeys.all });
      void queryClient.invalidateQueries({ queryKey: datasetKeys.detail(name) });
    },
  });
}

/** Delete a golden set; refreshes the list on success. (409-in-use is surfaced by the caller.) */
export function useDeleteDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDataset,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: datasetKeys.all });
    },
  });
}
