// Mirrors the API's EvalStatusResponse (api/.../schemas.py).
//
// The schema types `summary` loosely as dict[str, Any], but the producer
// (worker/.../evals/runner.py::_build_summary) always emits the exact shape below. We tighten it
// here so the eval dashboard is fully typed; treat fields as possibly-absent on older runs.

// A version's derived eval lifecycle. "completed" means scores are ready in `summary`.
export type EvalStatus =
  | "unevaluated"
  | "pending"
  | "running"
  | "completed"
  | "failed";

// Per-scorer rollup. pass_rate / mean_value are null when nothing was scored (distinct from 0).
export interface ScorerSummary {
  count: number;
  passed: number;
  pass_rate: number | null;
  mean_value: number | null;
}

// The run summary: per-scorer breakdown plus item/error totals.
export interface EvalSummary {
  items: number;
  scored: number;
  errors: number;
  scorers: Record<string, ScorerSummary>;
}

// Mirrors EvalStatusResponse — a version's eval state plus the latest run's summary.
export interface VersionEvalStatus {
  prompt: string;
  version_number: number;
  prompt_version_id: string;
  status: EvalStatus;
  latest_run_id: string | null;
  summary: EvalSummary | null;
}

// Mirrors EvalRunAccepted — the 202 body when an eval is triggered on demand (Sprint 16e).
export interface EvalRunAccepted {
  eval_run_id: string;
  status: string;
}

// Mirrors EvalRunSummary — one row in a version's eval run-history list (newest first).
// `summary` is the run's own aggregate rollup (same shape as a completed VersionEvalStatus's),
// present once it completes and null while pending/running or on failure.
export interface EvalRunSummary {
  id: string;
  status: EvalStatus;
  scorers: string[];
  created_at: string;
  completed_at: string | null;
  summary: EvalSummary | null;
}
