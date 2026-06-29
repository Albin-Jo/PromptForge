import type { AlertKind } from "./types";

// Presentation for each alert kind the API emits. The API owns *whether* an alert fires and its
// human `message`; the UI owns how the kind reads (a short label + a severity for badge colour and
// sort order). Mirrors the attention.ts pattern (overview), kept separate from the data types.

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";

interface AlertMeta {
  label: string;
  variant: BadgeVariant;
  // Higher = more urgent. Drives both the badge colour and the most-urgent-first ordering.
  severity: number;
}

export const ALERT_META: Record<AlertKind, AlertMeta> = {
  error_rate_high: { label: "Error rate", variant: "destructive", severity: 4 },
  quality_regression: { label: "Quality regression", variant: "destructive", severity: 3 },
  quality_below_threshold: { label: "Quality floor", variant: "warning", severity: 2 },
  cost_per_request_high: { label: "Cost", variant: "warning", severity: 1 },
};

// Fallback so an unknown future code still renders (badge + message) instead of a blank/crash.
const UNKNOWN_ALERT_META: AlertMeta = { label: "Alert", variant: "secondary", severity: 0 };

/** Presentation for a kind, falling back gracefully for a code the UI doesn't know yet. */
export function alertMeta(kind: string): AlertMeta {
  return (ALERT_META as Record<string, AlertMeta>)[kind] ?? UNKNOWN_ALERT_META;
}

/** "overall" → "Prompt-wide"; "version:3" → "Version 3"; anything else passes through unchanged. */
export function formatAlertScope(scope: string): string {
  if (scope === "overall") return "Prompt-wide";
  const match = /^version:(\d+)$/.exec(scope);
  return match ? `Version ${match[1]}` : scope;
}
