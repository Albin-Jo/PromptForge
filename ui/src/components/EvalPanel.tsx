import { useState } from "react";
import { usePromptMetrics } from "../lib/metrics/api";
import { formatPct, formatQuality } from "../lib/metrics/format";
import type { MetricsWindow, PromptMetrics } from "../lib/metrics/types";
import { isEvalRunning, useTriggerEval, useVersionEval } from "../lib/evals/api";
import type { EvalStatus, ScorerSummary, VersionEvalStatus } from "../lib/evals/types";
import { useCan } from "../lib/auth/AuthContext";
import { toast, toastError } from "../lib/toast";
import { QualityBar } from "./QualityBar";
import { QueryState } from "./QueryState";
import { RunActionButton } from "./RunActionButton";
import { Badge } from "./ui/badge";
import type { badgeVariants } from "./ui/badge";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
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

function EvalStatusBadge({ status }: { status: EvalStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

/** A pass/fail dot: green when every case passed, amber on a partial pass, red when none did. */
function PassDot({ passRate }: { passRate: number | null }) {
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

function EvalDetail({ data }: { data: VersionEvalStatus }) {
  if (data.status !== "completed" || !data.summary) {
    return (
      <div className="mt-3 flex items-center gap-3">
        <EvalStatusBadge status={data.status} />
        {data.status === "unevaluated" && (
          <span className="text-sm text-muted-foreground">No eval has run for this version.</span>
        )}
        {data.status === "failed" && (
          <span className="text-sm text-muted-foreground">
            The eval run errored — check the worker logs.
          </span>
        )}
      </div>
    );
  }

  const { summary } = data;
  const scorers = Object.entries(summary.scorers);
  return (
    <div className="mt-3">
      <EvalStatusBadge status={data.status} />
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

/** The across-versions quality table + the per-version detail selector. */
function EvalBody({ name, data }: { name: string; data: PromptMetrics }) {
  // Newest-first; default the detail selector to the latest version.
  const versions = [...data.by_version].sort((a, b) => b.version_number - a.version_number);
  const [selected, setSelected] = useState<number>(versions[0].version_number);
  // Poll so a triggered run is watched to completion (stops at completed/failed).
  const evalQuery = useVersionEval(name, selected, { poll: true });

  // On-demand eval is editor+. A run is "in flight" while the trigger is pending or the polled
  // status is still running.
  const canRun = useCan("editor");
  const triggerEval = useTriggerEval(name);
  const running =
    triggerEval.isPending ||
    (evalQuery.data ? isEvalRunning(evalQuery.data.status) : false);

  function runEval() {
    triggerEval.mutate(selected, {
      onSuccess: () => toast.success(`Started eval for v${selected}`),
      onError: (err) => toastError(err, "Could not start the eval."),
    });
  }

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Quality by version</CardTitle>
          <CardDescription>Mean eval quality for each version in this window.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Version</TableHead>
                <TableHead>Quality</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.map((v) => (
                <TableRow key={v.prompt_version_id}>
                  <TableCell className="font-medium text-foreground">v{v.version_number}</TableCell>
                  <TableCell>
                    <QualityBar value={v.quality} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Scorer breakdown</CardTitle>
              <CardDescription>Per-scorer pass rate for the selected version.</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Version</span>
                <Select value={String(selected)} onValueChange={(v) => setSelected(Number(v))}>
                  <SelectTrigger className="w-24" aria-label="Eval detail version">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {versions.map((v) => (
                      <SelectItem key={v.prompt_version_id} value={String(v.version_number)}>
                        v{v.version_number}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <RunActionButton
                onRun={runEval}
                running={running}
                canRun={canRun}
                idleLabel="Run eval"
                runningLabel="Running…"
                deniedReason="Requires the editor role"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <QueryState query={evalQuery} label="eval detail">
            {(detail) => <EvalDetail data={detail} />}
          </QueryState>
        </CardContent>
      </Card>
    </div>
  );
}

// The eval surface for one prompt: quality across versions (from the cached metrics call) plus
// the per-scorer pass/fail breakdown for a selected version (one /eval call).
export function EvalPanel({ name, window }: { name: string; window: MetricsWindow }) {
  const query = usePromptMetrics(name, window);

  return (
    <div className="mt-12">
      <h2 className="text-lg font-semibold">Eval scores</h2>
      <QueryState
        query={query}
        label="eval scores"
        isEmpty={(d) => d.by_version.length === 0}
        empty={<p className="mt-4 text-sm text-muted-foreground">No versions to evaluate yet.</p>}
      >
        {(data) => <EvalBody name={name} data={data} />}
      </QueryState>
    </div>
  );
}
