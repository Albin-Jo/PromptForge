// Mirrors the API's alert DTOs (api/.../schemas.py: AlertDTO & AlertsResponse; the firing logic
// lives in services/alerts.py). These are the drift/regression breaches currently firing for a
// prompt over a window — an empty `alerts` list means healthy.

// The stable machine codes the API emits today (services/alerts.py). The UI owns their wording and
// severity (see ./presentation); the API stays the source of truth, so presentation must also cope
// with an unknown code rather than assume this union is exhaustive forever.
export type AlertKind =
  | "error_rate_high"
  | "cost_per_request_high"
  | "quality_below_threshold"
  | "quality_regression";

// Mirrors AlertDTO. `observed` is what was measured, `threshold` the line it crossed.
export interface Alert {
  // A known AlertKind, or any future code the API adds — treat as a string defensively.
  kind: AlertKind | (string & {});
  // "overall" (prompt-wide) or "version:<n>" (a specific version's quality).
  scope: string;
  observed: number;
  threshold: number;
  message: string;
}

// Mirrors AlertsResponse — the alerts firing for one prompt over one window.
export interface PromptAlerts {
  name: string;
  window: string;
  alerts: Alert[];
}
