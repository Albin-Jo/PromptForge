// The eval run-history list for one prompt version (Sprint 24, T1): every persisted eval run,
// newest first, with drill-in to that run's scorer breakdown. The backend keeps every run; this
// surfaces them as an audit trail behind EvalPanel's latest-only status. The drill-in reuses
// EvalSummaryView so a historical run renders exactly like the live panel.

import { useState } from "react";
import { useVersionEvals } from "../lib/evals/api";
import type { EvalRunSummary, EvalSummary } from "../lib/evals/types";
import { formatPct, formatRelative } from "../lib/metrics/format";
import { EvalStatusBadge, EvalSummaryView, PassDot } from "./EvalSummaryView";
import { QueryState } from "./QueryState";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";

/** A run's overall pass rate across all its scorers (Σpassed / Σcount); null when nothing scored. */
export function overallPassRate(summary: EvalSummary | null): number | null {
  if (!summary) return null;
  let passed = 0;
  let count = 0;
  for (const scorer of Object.values(summary.scorers)) {
    passed += scorer.passed;
    count += scorer.count;
  }
  return count === 0 ? null : passed / count;
}

function RunRow({ run }: { run: EvalRunSummary }) {
  const [open, setOpen] = useState(false);
  const passRate = overallPassRate(run.summary);

  function toggle() {
    setOpen((v) => !v);
  }

  return (
    <>
      <TableRow
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        className="cursor-pointer"
      >
        <TableCell
          className="font-medium text-foreground"
          title={new Date(run.created_at).toLocaleString()}
        >
          {formatRelative(run.created_at)}
        </TableCell>
        <TableCell className="text-muted-foreground">{run.scorers.join(", ") || "—"}</TableCell>
        <TableCell className="text-right text-muted-foreground">{formatPct(passRate)}</TableCell>
        <TableCell>
          <span className="flex items-center gap-2">
            <PassDot passRate={passRate} />
            <EvalStatusBadge status={run.status} />
          </span>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={4} className="bg-muted/30">
            <EvalSummaryView status={run.status} summary={run.summary} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export function EvalRunsList({
  name,
  versionNumber,
}: {
  name: string | undefined;
  versionNumber: number | undefined;
}) {
  // Poll so a freshly triggered run flips from in-progress to scored without a manual refresh.
  const query = useVersionEvals(name, versionNumber, { poll: true });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Eval runs</CardTitle>
        <CardDescription>Every eval for this version, newest first.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState
          query={query}
          label="eval runs"
          isEmpty={(runs) => runs.length === 0}
          empty={
            <p className="text-sm text-muted-foreground">No evals have run for this version yet.</p>
          }
        >
          {(runs) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Scorers</TableHead>
                  <TableHead className="text-right">Pass rate</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </TableBody>
            </Table>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}
