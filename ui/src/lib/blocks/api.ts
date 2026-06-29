import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api";
import type {
  Block,
  BlockCreate,
  BlockImpact,
  BlockVersion,
  BlockVersionCreate,
} from "./types";

export const blockKeys = {
  all: ["blocks"] as const,
  detail: (name: string) => ["block", name] as const,
  versions: (name: string) => ["block-versions", name] as const,
  impact: (name: string) => ["block-impact", name] as const,
};

export function listBlocks(signal?: AbortSignal): Promise<Block[]> {
  return apiFetch<Block[]>("/blocks", { signal });
}

export function getBlock(name: string, signal?: AbortSignal): Promise<Block> {
  return apiFetch<Block>(`/blocks/${encodeURIComponent(name)}`, { signal });
}

export function listBlockVersions(name: string, signal?: AbortSignal): Promise<BlockVersion[]> {
  return apiFetch<BlockVersion[]>(`/blocks/${encodeURIComponent(name)}/versions`, { signal });
}

export function getBlockVersion(
  name: string,
  versionNumber: number,
  signal?: AbortSignal,
): Promise<BlockVersion> {
  return apiFetch<BlockVersion>(
    `/blocks/${encodeURIComponent(name)}/versions/${versionNumber}`,
    { signal },
  );
}

export function getBlockImpact(name: string, signal?: AbortSignal): Promise<BlockImpact> {
  return apiFetch<BlockImpact>(`/blocks/${encodeURIComponent(name)}/impact`, { signal });
}

export function createBlock(body: BlockCreate): Promise<Block> {
  return apiFetch<Block>("/blocks", { method: "POST", body });
}

export function createBlockVersion(name: string, body: BlockVersionCreate): Promise<BlockVersion> {
  return apiFetch<BlockVersion>(`/blocks/${encodeURIComponent(name)}/versions`, {
    method: "POST",
    body,
  });
}

/** Server-state hook for the full block catalog (list page + the composition picker). */
export function useBlocks() {
  return useQuery({
    queryKey: blockKeys.all,
    queryFn: ({ signal }) => listBlocks(signal),
  });
}

/** Server-state hook for one block with its version history. Disabled until a name is given. */
export function useBlock(name: string | undefined) {
  return useQuery({
    queryKey: blockKeys.detail(name ?? ""),
    queryFn: ({ signal }) => getBlock(name as string, signal),
    enabled: Boolean(name),
  });
}

/** Impact analysis for one block. Disabled until `enabled` — we fetch on demand only. */
export function useBlockImpact(name: string, enabled: boolean) {
  return useQuery({
    queryKey: blockKeys.impact(name),
    queryFn: ({ signal }) => getBlockImpact(name, signal),
    enabled,
  });
}

/**
 * Create a block (+ its first version). Refreshes the catalog so it shows up everywhere it's listed
 * — including the composition picker, which reads the same `blockKeys.all` query.
 */
export function useCreateBlock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createBlock,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: blockKeys.all });
    },
  });
}

/**
 * Append a new version to a block. Refreshes the catalog (latest version changed) plus that block's
 * detail/version history. The composition picker re-pins to the new latest on next add.
 */
export function useCreateBlockVersion(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BlockVersionCreate) => createBlockVersion(name, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: blockKeys.all });
      void queryClient.invalidateQueries({ queryKey: blockKeys.detail(name) });
      void queryClient.invalidateQueries({ queryKey: blockKeys.versions(name) });
    },
  });
}
