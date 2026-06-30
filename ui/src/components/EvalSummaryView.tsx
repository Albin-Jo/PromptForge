// Shared rendering for one eval run's aggregate result: the status badge plus, once completed,
// the per-scorer pass/fail breakdown. Extracted from EvalPanel so the live per-version panel
// (EvalPanel) and the historical run-history drill-in (EvalRunsList) render an eval the same way
// rather than forking the markup (Sprint 24, T1).

import type { EvalStatus, EvalSummary, ScorerSummary } from "../lib/evals/types";
import { formatPct, formatQuality } from "../lib/metrics/format";
import { Badge } from "./ui/badge";
import type { badgeVariants } from "./ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";
import type { VariantProps } from "class-variance-authority";

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

// How each eval lifecycle state reads, and which shared Badge variant carries its colour.
const STATUS_LABEL: Record<EvalStatus, string> = {
  unevaluated: "Not evaluated yet",
  pending: "In progress",
  running: "In progress",
  completed: "Evaluated",
  failed: "Eval failed",
};

const STATUS_VARIANT: Record<EvalStatus, BadgeVariant> = {
  unevaluated: "secondary",
  pending: "warning",
  running: "warning",
  completed: "success",
  failed: "destructive",
};

export function EvalStatusBadge({ status }: { status: EvalStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

/** A pass/fail dot: green when every case passed, amber on a partial pass, red when none did. */
export function PassDot({ passRate }: { passRate: number | null }) {
  const color =
    passRate === null
      ? "bg-muted-foreground/40"
      : passRate === 1
        ? "bg-success"
        : passRate === 0
          ? "bg-destructive"
          : "bg-warning";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} aria-hidden />;
}

function ScorerRow({ name, scorer }: { name: string; scorer: ScorerSummary }) {
  return (
    <TableRow>
      <TableCell className="font-medium text-foreground">
        <span className="flex items-center gap-2">
          <PassDot passRate={scorer.pass_rate} />
          {name}
        </span>
      </TableCell>
      <TableCell className="text-right text-muted-foreground">
        {scorer.passed}/{scorer.count}
      </TableCell>
      <TableCell className="text-right text-muted-foreground">{formatPct(scorer.pass_rate)}</TableCell>
      <TableCell className="text-right text-muted-foreground">{formatQuality(scorer.mean_value)}</TableCell>
    </TableRow>
  );
}

/**
 * Render one eval's aggregate result. `completed` + a summary shows the scorer breakdown; any
 * other state shows just the badge and an optional context line (the panel passes one for the
 * never-run case, which can't occur for a real persisted run).
 */
export function EvalSummaryView({
  status,
  summary,
  emptyMessage,
}: {
  status: EvalStatus;
  summary: EvalSummary | null;
  emptyMessage?: string;
}) {
  if (status !== "completed" || !summary) {
    return (
      <div className="mt-3 flex items-center gap-3">
        <EvalStatusBadge status={status} />
        {status === "unevaluated" && emptyMessage && (
          <span className="text-sm text-muted-foreground">{emptyMessage}</span>
        )}
        {status === "failed" && (
          <span className="text-sm text-muted-foreground">
            The eval run errored — check the worker logs.
          </span>
        )}
      </div>
    );
  }

  const scorers = Object.entries(summary.scorers);
  return (
    <div className="mt-3">
      <EvalStatusBadge status={status} />
      <Table className="mt-3">
        <TableHeader>
          <TableRow>
            <TableHead>Scorer</TableHead>
            <TableHead className="text-right">Passed</TableHead>
            <TableHead className="text-right">Pass rate</TableHead>
            <TableHead className="text-right">Mean</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {scorers.map(([name, scorer]) => (
            <ScorerRow key={name} name={name} scorer={scorer} />
          ))}
        </TableBody>
      </Table>
      <p className="mt-2 text-xs text-muted-foreground">
        {summary.items} item{summary.items === 1 ? "" : "s"} · {summary.scored} scored ·{" "}
        {summary.errors} error{summary.errors === 1 ? "" : "s"}
      </p>
    </div>
  );
}
