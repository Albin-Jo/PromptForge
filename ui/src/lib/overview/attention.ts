import type { AttentionRule } from "./types";

// Presentation for each "needs attention" rule key the API emits (services/overview.py owns the
// firing logic; the UI owns the wording + badge style). Keeping this here means a new rule is a
// single edit and the union type forces every rule to have a presentation.

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

export const ATTENTION_META: Record<
  AttentionRule,
  { label: string; description: string; variant: BadgeVariant }
> = {
  high_error_rate: {
    label: "High errors",
    description: "Error rate above 5% in this window",
    variant: "destructive",
  },
  unscanned_or_risky: {
    label: "Scan",
    description: "Latest version is unscanned or flagged high-risk",
    variant: "secondary",
  },
  failing_or_missing_eval: {
    label: "Eval",
    description: "Latest version is unevaluated or below the quality floor",
    variant: "secondary",
  },
  no_recent_traffic: {
    label: "Idle",
    description: "An established prompt with no requests in this window",
    variant: "outline",
  },
};

// Most-urgent first — used to order both the badges on a row and the rows in the list.
export const ATTENTION_ORDER: AttentionRule[] = [
  "high_error_rate",
  "unscanned_or_risky",
  "failing_or_missing_eval",
  "no_recent_traffic",
];

/** A severity score for sorting: more (and more urgent) flags float to the top of the list. */
export function attentionWeight(rules: AttentionRule[]): number {
  return rules.reduce((sum, r) => sum + (ATTENTION_ORDER.length - ATTENTION_ORDER.indexOf(r)), 0);
}
