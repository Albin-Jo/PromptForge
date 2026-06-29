import type { EvalSummary } from "../evals/types";

// Mirrors the API's PromptSummaryRead schema (api/.../schemas.py).
export interface PromptSummary {
  name: string;
  description: string | null;
  latest_version: number | null;
  version_count: number;
  created_at: string;
  updated_at: string;
}

// Mirrors BlockRefDTO — a pinned reference to an exact block version.
export interface BlockRef {
  block: string;
  version: number;
}

// Mirrors PromptVersionRead.
export interface PromptVersion {
  id: string;
  version_number: number;
  parent_version_id: string | null;
  content: string;
  input_variables: string[];
  model_settings: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  created_at: string;
  blocks: BlockRef[];
}

// Mirrors PromptRead.
export interface Prompt {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  versions: PromptVersion[];
  // The golden set this prompt must clear to be promoted, by id (null = no gate attached).
  golden_set_id: string | null;
}

// Shared version body, mirrors VersionContent.
export interface VersionContent {
  content: string;
  input_variables: string[];
  model_settings?: Record<string, unknown> | null;
  output_schema?: Record<string, unknown> | null;
  blocks?: BlockRef[];
}

// Request body for POST /prompts.
export interface PromptCreate extends VersionContent {
  name: string;
  description?: string | null;
}

// Request body for POST /prompts/:name/versions.
export type VersionCreate = VersionContent;

// Mirrors RenderResponse — a finished prompt plus the version's model config.
export interface RenderResponse {
  prompt: string;
  model_settings: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  prompt_id: string;
  prompt_version_id: string;
  version_number: number;
}

// --- Labels / promotion (Sprint 16e) ---------------------------------------

// Mirrors LabelRead — the 200 body of PUT /prompts/{name}/labels/{label}.
export interface LabelRead {
  name: string;
  version: PromptVersion;
}

// One scorer's candidate-vs-baseline comparison inside a blocked promotion.
// Mirrors the per-scorer deltas the gate emits (api/.../services + promotion policy).
export interface PromotionDelta {
  scorer: string;
  candidate: number | null;
  baseline: number | null;
  drop: number | null;
  floor_ok: boolean;
  regression: boolean;
}

// Mirrors the `promotion` object on a 409-blocked label move: why it was refused, per metric.
export interface PromotionResult {
  allowed: boolean;
  reasons: string[];
  regression_checked: boolean;
  deltas: PromotionDelta[];
  eval_run_id: string;
  candidate_summary: EvalSummary | null;
  production_eval_run_id: string | null;
  from_version: number | null;
  to_version: number;
}

// The two distinct 409 bodies a promote can return. Both reach the UI as ApiError.body
// (apiFetch throws on non-2xx but preserves the parsed body); the dialog branches on them.
//   - blocked: the gate refused — `promotion` carries the per-metric detail to render.
//   - pending: the gate hasn't finished — poll the returned run/scan id, then retry.
export interface PromotionBlockedBody {
  detail: string;
  promotion: PromotionResult;
}

export interface PromotionPendingBody {
  detail: string;
  eval_run_id?: string;
  security_scan_id?: string;
}
