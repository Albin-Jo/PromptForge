import { useState } from "react";

import { InfoHint } from "./InfoHint";
import { QueryState } from "./QueryState";
import { TrendChart } from "./charts/TrendChart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Skeleton } from "./ui/skeleton";
import { usePromptMetrics, usePromptTimeseries } from "../lib/metrics/api";
import { formatCost, formatMs, formatPct, formatQuality } from "../lib/metrics/format";
import { formatBucketLabel, formatBucketTick } from "../lib/metrics/timeseries";
import type { ChartDatum } from "./ui/chart";
import type { MetricsWindow, PromptTimeseries, VersionMetrics } from "../lib/metrics/types";

function VersionSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: number;
  options: number[];
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
        <SelectTrigger className="w-24" aria-label={`Version ${label}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((n) => (
            <SelectItem key={n} value={String(n)}>
              v{n}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

// Zip two version-scoped series into one row set keyed by bucket — they share a spine (same window
// + interval), so the bucket_start values line up. Nulls (empty buckets) are preserved as gaps.
function mergeTrends(a: PromptTimeseries, b: PromptTimeseries): ChartDatum[] {
  const bByBucket = new Map(b.buckets.map((x) => [x.bucket_start, x.request_count]));
  return a.buckets.map((x) => ({
    bucket: x.bucket_start,
    a: x.request_count,
    b: bByBucket.get(x.bucket_start) ?? null,
  }));
}

function ComparisonTable({
  labelA,
  labelB,
  a,
  b,
}: {
  labelA: string;
  labelB: string;
  a: VersionMetrics | undefined;
  b: VersionMetrics | undefined;
}) {
  const rows: { metric: string; hint?: string; a: string; b: string }[] = [
    {
      metric: "Requests",
      a: a?.metrics.request_count.toLocaleString() ?? "—",
      b: b?.metrics.request_count.toLocaleString() ?? "—",
    },
    {
      metric: "Error rate",
      a: formatPct(a?.metrics.error_rate ?? null),
      b: formatPct(b?.metrics.error_rate ?? null),
    },
    {
      metric: "p95 latency (ms)",
      a: formatMs(a?.metrics.latency.p95_ms ?? null),
      b: formatMs(b?.metrics.latency.p95_ms ?? null),
    },
    {
      metric: "Cost (USD)",
      a: formatCost(a?.metrics.total_cost_usd ?? null),
      b: formatCost(b?.metrics.total_cost_usd ?? null),
    },
    {
      metric: "Quality (0–1)",
      hint: "Eval quality score from 0 to 1 — higher is better, 1.0 is perfect.",
      a: formatQuality(a?.quality ?? null),
      b: formatQuality(b?.quality ?? null),
    },
  ];

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-muted-foreground border-border border-b text-left">
          <th className="py-2 font-medium">Metric</th>
          <th className="py-2 text-right font-medium">{labelA}</th>
          <th className="py-2 text-right font-medium">{labelB}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.metric} className="border-border/60 border-b">
            <td className="text-muted-foreground py-2">
              <span className="inline-flex items-center gap-1">
                {r.metric}
                {r.hint && <InfoHint text={r.hint} />}
              </span>
            </td>
            <td className="py-2 text-right tabular-nums">{r.a}</td>
            <td className="py-2 text-right tabular-nums">{r.b}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ComparisonBody({
  name,
  window,
  versions,
}: {
  name: string;
  window: MetricsWindow;
  versions: VersionMetrics[];
}) {
  const nums = versions.map((v) => v.version_number).sort((x, y) => x - y);
  // Default to the two latest versions — the most common "did my last change help?" comparison.
  const [a, setA] = useState(nums[nums.length - 2]);
  const [b, setB] = useState(nums[nums.length - 1]);

  const qa = usePromptTimeseries(name, window, undefined, a);
  const qb = usePromptTimeseries(name, window, undefined, b);
  const vmA = versions.find((v) => v.version_number === a);
  const vmB = versions.find((v) => v.version_number === b);

  const ready = qa.data && qb.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <VersionSelect label="A" value={a} options={nums} onChange={setA} />
        <VersionSelect label="B" value={b} options={nums} onChange={setB} />
      </div>

      {ready ? (
        <TrendChart
          data={mergeTrends(qa.data, qb.data)}
          xKey="bucket"
          series={[
            { key: "a", label: `v${a}`, color: "var(--chart-1)" },
            { key: "b", label: `v${b}`, color: "var(--chart-2)" },
          ]}
          className="aspect-[3/1] w-full"
          xTickFormatter={(v) => formatBucketTick(v, qa.data.interval)}
          tooltipLabelFormatter={(v) => formatBucketLabel(v, qa.data.interval)}
          tooltipValueFormatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v ?? "—"))}
        />
      ) : (
        <Skeleton className="aspect-[3/1] w-full" />
      )}

      <ComparisonTable labelA={`v${a}`} labelB={`v${b}`} a={vmA} b={vmB} />
    </div>
  );
}

// Pick two versions and compare their traffic trend + headline metrics side by side. Self-fetches
// the aggregate metrics (shared react-query cache with the panel above) and a version-scoped
// time-series per selected version (the per-version filter added for the dashboard sparklines).
export function VersionComparison({ name, window }: { name: string; window: MetricsWindow }) {
  const query = usePromptMetrics(name, window);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Compare versions</CardTitle>
        <CardDescription>Traffic trend and headline metrics for two versions.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState
          query={query}
          label="metrics"
          isEmpty={(d) => d.by_version.length < 2}
          empty={
            <p className="text-muted-foreground text-sm">
              Add a second version to compare — there's only one with traffic in this window.
            </p>
          }
        >
          {(data) => <ComparisonBody name={name} window={window} versions={data.by_version} />}
        </QueryState>
      </CardContent>
    </Card>
  );
}
