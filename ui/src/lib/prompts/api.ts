import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "../api";
import type {
  LabelRead,
  Prompt,
  PromptCreate,
  PromotionBlockedBody,
  PromotionPendingBody,
  PromptSummary,
  PromptVersion,
  RenderResponse,
  VersionCreate,
} from "./types";

/**
 * Classify a failed promote. A 409 is a *refusal/state*, not an error, and comes in two shapes:
 *   - blocked: the gate said no — the body carries `promotion` (per-metric detail).
 *   - pending: the gate hasn't finished — the body carries an eval_run_id/security_scan_id to poll.
 * Anything else (403, 500, a non-ApiError) is a real failure for the caller to surface generically.
 */
export function asPromotionBlocked(err: unknown): PromotionBlockedBody | null {
  if (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.body === "object" &&
    err.body !== null &&
    "promotion" in err.body
  ) {
    return err.body as PromotionBlockedBody;
  }
  return null;
}

export function asPromotionPending(err: unknown): PromotionPendingBody | null {
  if (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.body === "object" &&
    err.body !== null &&
    !("promotion" in err.body) &&
    ("eval_run_id" in err.body || "security_scan_id" in err.body)
  ) {
    return err.body as PromotionPendingBody;
  }
  return null;
}

export const promptKeys = {
  all: ["prompts"] as const,
  detail: (name: string) => ["prompt", name] as const,
};

export const labelKeys = {
  // One resolved label pointer (production/staging → version). Drives the live label badges.
  detail: (name: string, label: string) => ["label", name, label] as const,
};

export function listPrompts(signal?: AbortSignal): Promise<PromptSummary[]> {
  return apiFetch<PromptSummary[]>("/prompts", { signal });
}

export function getPrompt(name: string, signal?: AbortSignal): Promise<Prompt> {
  return apiFetch<Prompt>(`/prompts/${encodeURIComponent(name)}`, { signal });
}

export function createPrompt(body: PromptCreate): Promise<Prompt> {
  return apiFetch<Prompt>("/prompts", { method: "POST", body });
}

export function createVersion(name: string, body: VersionCreate): Promise<PromptVersion> {
  return apiFetch<PromptVersion>(`/prompts/${encodeURIComponent(name)}/versions`, {
    method: "POST",
    body,
  });
}

/** Render a version with variables into a finished prompt + its model config (playground). */
export function renderVersion(
  name: string,
  versionNumber: number,
  variables: Record<string, string>,
): Promise<RenderResponse> {
  return apiFetch<RenderResponse>(
    `/prompts/${encodeURIComponent(name)}/versions/${versionNumber}/render`,
    { method: "POST", body: { variables } },
  );
}

/**
 * Point a label at a version (the promote/deploy call). Moving the *gated* label runs the quality
 * gate, so this can 409: blocked (body carries `promotion`) or pending (body carries an
 * eval_run_id/security_scan_id). We let apiFetch throw `ApiError` and the caller reads `err.body` —
 * a 409 is a refusal/state, not a failure, so we don't swallow it here (Sprint 16e).
 */
export function setLabel(
  name: string,
  label: string,
  versionNumber: number,
): Promise<LabelRead> {
  return apiFetch<LabelRead>(
    `/prompts/${encodeURIComponent(name)}/labels/${encodeURIComponent(label)}`,
    { method: "PUT", body: { version_number: versionNumber } },
  );
}

/** Resolve a label to the version it currently points at, or null when the label is unset (404). */
export async function resolveLabel(
  name: string,
  label: string,
  signal?: AbortSignal,
): Promise<PromptVersion | null> {
  try {
    return await apiFetch<PromptVersion>(
      `/prompts/${encodeURIComponent(name)}/labels/${encodeURIComponent(label)}`,
      { signal },
    );
  } catch (err) {
    // An unset label is a normal state, not an error — surface it as "no version".
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** Server-state hook for one resolved label (null when unset). Drives the live promote badges. */
export function useResolveLabel(name: string | undefined, label: string) {
  return useQuery({
    queryKey: labelKeys.detail(name ?? "", label),
    queryFn: ({ signal }) => resolveLabel(name as string, label, signal),
    enabled: Boolean(name),
  });
}

/**
 * Promote a version to a label. On success, re-resolve every label badge for this prompt so it
 * moves to the new version. (We don't invalidate the prompt detail: a label move doesn't change the
 * version history.) On 409 the mutation rejects with an `ApiError` whose `.body` the dialog inspects
 * (blocked-with-scores vs pending) — we intentionally don't catch it here.
 */
export function useSetLabel(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ label, versionNumber }: { label: string; versionNumber: number }) =>
      setLabel(name, label, versionNumber),
    onSuccess: () => {
      // Re-resolve any label badges for this prompt (keys are ["label", name, <label>]).
      void queryClient.invalidateQueries({
        predicate: (q) => q.queryKey[0] === "label" && q.queryKey[1] === name,
      });
    },
  });
}

/** Point a prompt at the golden set it must clear to be promoted. */
export function attachGoldenSet(name: string, dataset: string): Promise<Prompt> {
  return apiFetch<Prompt>(`/prompts/${encodeURIComponent(name)}/golden-set`, {
    method: "PUT",
    body: { dataset },
  });
}

/** Clear a prompt's golden set (so it has no promotion gate, and that set can be deleted). */
export function detachGoldenSet(name: string): Promise<Prompt> {
  return apiFetch<Prompt>(`/prompts/${encodeURIComponent(name)}/golden-set`, { method: "DELETE" });
}

/**
 * Attach or detach a prompt's golden set, then refresh that prompt's detail so the attached-set
 * indicator reflects the change. `dataset === null` detaches.
 */
export function useSetGoldenSet(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dataset: string | null) =>
      dataset === null ? detachGoldenSet(name) : attachGoldenSet(name, dataset),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: promptKeys.detail(name) });
    },
  });
}

/** Server-state hook for the prompt list. */
export function usePrompts() {
  return useQuery({
    queryKey: promptKeys.all,
    queryFn: ({ signal }) => listPrompts(signal),
  });
}

/** Server-state hook for one prompt (with version history). Disabled until a name is given. */
export function usePrompt(name: string | undefined) {
  return useQuery({
    queryKey: promptKeys.detail(name ?? ""),
    queryFn: ({ signal }) => getPrompt(name as string, signal),
    enabled: Boolean(name),
  });
}

/** Create a new prompt; refreshes the list on success. */
export function useCreatePrompt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPrompt,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: promptKeys.all });
    },
  });
}

/** Append a version to an existing prompt; refreshes the list + that prompt's detail. */
export function useCreateVersion(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: VersionCreate) => createVersion(name, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: promptKeys.all });
      void queryClient.invalidateQueries({ queryKey: promptKeys.detail(name) });
    },
  });
}
