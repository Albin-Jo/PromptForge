import type { Severity } from "./types";

// Presentation for scan severities — the API owns the finding data; the UI owns how a severity reads
// (its Badge colour). Shared by the full scan page and the dashboard scan panel so the two never
// drift (16d dedup). Mirrors the alerts/presentation.ts pattern; kept free of component imports.

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";

// high=danger, medium=warning, low=neutral, none=clean/success.
export const SEVERITY_VARIANT: Record<Severity | "none", BadgeVariant> = {
  high: "destructive",
  medium: "warning",
  low: "secondary",
  none: "success",
};
