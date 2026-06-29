import { useState } from "react";

import { QueryState } from "./QueryState";
import { Sparkline } from "./charts/Sparkline";
import { TrendChart } from "./charts/TrendChart";
import { MetricBarChart } from "./charts/MetricBarChart";
import { Badge } from "./ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Skeleton } from "./ui/skeleton";
import { usePromptMetrics, usePromptTimeseries } from "../lib/metrics/api";
import { useResolveLabel } from "../lib/prompts/api";
import { labelVariant } from "../lib/prompts/labels";
import { formatCost, formatMs, formatPct, formatQuality, formatRelative } from "../lib/metrics/format";
import { bucketsToTrend, formatBucketLabel, formatBucketTick, isEmptySeries } from "../lib/metrics/timeseries";
import type { MetricsWindow, PromptMetrics, VersionMetrics } from "../lib/metrics/types";

/** One headline number as a compact tile. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="px-4">
        <div className="text-muted-foreground text-xs tracking-wide uppercase">{label}</div>
        <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      </CardContent>
    </Card>
  );
}

function OverallStats({ data }: { data: PromptMetrics }) {
  const { overall } = data;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <Stat label="Requests" value={overall.request_count.toLocaleString()} />
      <Stat label="Errors" value={overall.error_count.toLocaleString()} />
      <Stat label="Error rate" value={formatPct(overall.error_rate)} />
      <Stat label="p50" value={formatMs(overall.latency.p50_ms)} />
      <Stat label="p95" value={formatMs(overall.latency.p95_ms)} />
      <Stat label="Cost" value={formatCost(overall.total_cost_usd)} />
    </div>
  );
}

// Merge aggregate trend rows with a version-scoped series into a single chart data array.
// The two series share a bucket spine (same window + interval), so alignment is by bucket_start.
function mergeVersionTrend(
  aggregate: ReturnType<typeof bucketsToTrend>,
  version: ReturnType<typeof bucketsToTrend>,
) {
  const vByBucket = new Map(version.map((d) => [d.bucket, d]));
  return aggregate.map((a) => ({
    ...a,
    v_requests: vByBucket.get(a.bucket)?.requests ?? null,
    v_p95: vByBucket.get(a.bucket)?.p95 ?? null,
    v_quality: vByBucket.get(a.bucket)?.quality ?? null,
  }));
}

// The prompt-level trends — traffic, latency, and quality over the window — from one time-series
// query. When a version is selected via the overlay selector, a second version-scoped series is
// fetched and merged onto each chart so you can compare one version against the aggregate.
function Trends({
  name,
  window,
  versions,
}: {
  name: string;
  window: MetricsWindow;
  versions: number[];
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | undefined>(undefined);

  const query = usePromptTimeseries(name, window);
  const versionQuery = usePromptTimeseries(name, window, undefined, selectedVersion);

  return (
    <QueryState
      query={query}
      label="trend"
      loading={<Skeleton className="aspect-[3/1] w-full" />}
      isEmpty={isEmptySeries}
      empty={<p className="text-muted-foreground text-sm">No traffic in this window.</p>}
    >
      {(d) => {
        const aggregate = bucketsToTrend(d.buckets);
        const versionData =
          selectedVersion !== undefined && versionQuery.data
            ? bucketsToTrend(versionQuery.data.buckets)
            : null;
        const trend = versionData ? mergeVersionTrend(aggregate, versionData) : aggregate;
        const tick = (v: unknown) => formatBucketTick(v, d.interval);
        const tipLabel = (v: unknown) => formatBucketLabel(v, d.interval);
        const vLabel = selectedVersion !== undefined ? `v${selectedVersion}` : "";

        return (
          <div className="space-y-4">
            {versions.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-sm">Version overlay</span>
                <Select
                  value={selectedVersion !== undefined ? String(selectedVersion) : "all"}
                  onValueChange={(v) =>
                    setSelectedVersion(v === "all" ? undefined : Number(v))
                  }
                >
                  <SelectTrigger className="h-7 w-36 text-xs" aria-label="Version overlay">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All versions</SelectItem>
                    {versions.map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        v{n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Traffic</CardTitle>
                  <CardDescription>Requests over the window, across all versions.</CardDescription>
                </CardHeader>
                <CardContent>
                  <TrendChart
                    data={trend}
                    xKey="bucket"
                    variant="area"
                    series={
                      versionData
                        ? [
                            { key: "requests", label: "All versions", color: "var(--chart-1)" },
                            { key: "v_requests", label: vLabel, color: "var(--chart-4)" },
                          ]
                        : [{ key: "requests", label: "Requests", color: "var(--chart-1)" }]
                    }
                    className="aspect-[3/1] w-full"
                    xTickFormatter={tick}
                    tooltipLabelFormatter={tipLabel}
                    tooltipValueFormatter={(v) =>
                      typeof v === "number" ? v.toLocaleString() : String(v ?? "—")
                    }
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Latency</CardTitle>
                  <CardDescription>
                    {versionData
                      ? `p95 — all versions vs ${vLabel}.`
                      : "p50 / p95 / p99 latency per bucket."}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <TrendChart
                    data={trend}
                    xKey="bucket"
                    series={
                      versionData
                        ? [
                            { key: "p95", label: "p95 (all)", color: "var(--chart-3)" },
                            { key: "v_p95", label: `p95 (${vLabel})`, color: "var(--chart-4)" },
                          ]
                        : [
                            { key: "p50", label: "p50", color: "var(--chart-2)" },
                            { key: "p95", label: "p95", color: "var(--chart-3)" },
                            { key: "p99", label: "p99", color: "var(--chart-1)" },
                          ]
                    }
                    className="aspect-[3/1] w-full"
                    xTickFormatter={tick}
                    tooltipLabelFormatter={tipLabel}
                    tooltipValueFormatter={(v) =>
                      typeof v === "number" ? formatMs(v) : String(v ?? "—")
                    }
                  />
                </CardContent>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-base">Quality</CardTitle>
                  <CardDescription>Mean eval quality per bucket (gaps = no eval).</CardDescription>
                </CardHeader>
                <CardContent>
                  <TrendChart
                    data={trend}
                    xKey="bucket"
                    series={
                      versionData
                        ? [
                            { key: "quality", label: "All versions", color: "var(--chart-2)" },
                            { key: "v_quality", label: vLabel, color: "var(--chart-4)" },
                          ]
                        : [{ key: "quality", label: "Quality", color: "var(--chart-2)" }]
                    }
                    className="aspect-[4/1] w-full"
                    yDomain={[0, 1]}
                    xTickFormatter={tick}
                    tooltipLabelFormatter={tipLabel}
                    tooltipValueFormatter={(v) =>
                      typeof v === "number" ? formatQuality(v) : String(v ?? "—")
                    }
                  />
                </CardContent>
              </Card>
            </div>
          </div>
        );
      }}
    </QueryState>
  );
}

// A per-version request-trend sparkline — its own version-scoped time-series query.
function VersionSparkline({
  name,
  window,
  version,
}: {
  name: string;
  window: MetricsWindow;
  version: number;
}) {
  const query = usePromptTimeseries(name, window, undefined, version);
  if (query.isPending) return <Skeleton className="h-6 w-24" />;
  if (query.isError || !query.data) return <span className="text-muted-foreground">—</span>;

  const series = query.data.buckets.map((b) => b.request_count);
  if (!series.some((v) => v > 0)) {
    return <span className="text-muted-foreground text-xs">no traffic</span>;
  }
  return (
    <Sparkline
      data={series}
      color="var(--chart-1)"
      width={96}
      height={24}
      aria-label={`v${version} request trend`}
    />
  );
}

function VersionRow({
  name,
  window,
  version,
  liveLabels,
}: {
  name: string;
  window: MetricsWindow;
  version: VersionMetrics;
  liveLabels: string[];
}) {
  const { metrics } = version;
  return (
    <tr className="border-border/60 border-b">
      <td className="py-2 font-medium">
        <span className="flex items-center gap-2">
          v{version.version_number}
          {liveLabels.map((l) => (
            <Badge key={l} variant={labelVariant(l)} className="text-[10px]">
              {l}
            </Badge>
          ))}
        </span>
      </td>
      <td className="py-2">
        <VersionSparkline name={name} window={window} version={version.version_number} />
      </td>
      <td className="text-muted-foreground py-2 text-right">
        {metrics.request_count.toLocaleString()}
      </td>
      <td className="text-muted-foreground py-2 text-right">{formatPct(metrics.error_rate)}</td>
      <td className="text-muted-foreground py-2 text-right">{formatMs(metrics.latency.p95_ms)}</td>
      <td className="text-muted-foreground py-2 text-right">{formatCost(metrics.total_cost_usd)}</td>
    </tr>
  );
}

function ByVersion({ data, name, window }: { data: PromptMetrics; name: string; window: MetricsWindow }) {
  // Resolve the live label pointers so the row that's actually serving traffic is marked. Shares
  // the dashboard header's cache entries (same keys) — no extra fetch.
  const production = useResolveLabel(name, "production");
  const staging = useResolveLabel(name, "staging");
  const labelsFor = (version: number): string[] => {
    const out: string[] = [];
    if (production.data?.version_number === version) out.push("production");
    if (staging.data?.version_number === version) out.push("staging");
    return out;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">By version</CardTitle>
        <CardDescription>Each version's traffic, errors, latency, and cost (quality lives under Eval scores).</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-muted-foreground border-border border-b text-left">
              <th className="py-2 font-medium">Version</th>
              <th className="py-2 font-medium">Trend</th>
              <th className="py-2 text-right font-medium">Requests</th>
              <th className="py-2 text-right font-medium">Error rate</th>
              <th className="py-2 text-right font-medium">p95</th>
              <th className="py-2 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {data.by_version.map((v) => (
              <VersionRow
                key={v.prompt_version_id}
                name={name}
                window={window}
                version={v}
                liveLabels={labelsFor(v.version_number)}
              />
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function CostBySource({ data }: { data: PromptMetrics }) {
  if (data.by_source.length === 0) return null;
  // Number() is for bar *position* only; the table/tooltip format the exact decimal string.
  const rows = data.by_source.map((s) => ({
    source: s.source ?? "(unattributed)",
    cost: Number(s.cost_usd ?? 0),
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Cost by source</CardTitle>
        <CardDescription>Spend attributed per feature/source.</CardDescription>
      </CardHeader>
      <CardContent>
        <MetricBarChart
          data={rows}
          xKey="source"
          valueKey="cost"
          label="Cost (USD)"
          color="var(--chart-2)"
          layout="vertical"
          className="aspect-[2/1] w-full"
          yTickFormatter={(v) => formatCost(String(v))}
          tooltipValueFormatter={(v) => (v == null ? "—" : formatCost(String(v)))}
        />
      </CardContent>
    </Card>
  );
}

// The observability surface for one prompt: latency / error / cost / quality over a window —
// charts + retained detail tables. The window selector lives in the dashboard header (so the one
// visible control drives every panel); this panel just consumes the window prop.
export function ObservabilityPanel({
  name,
  window,
}: {
  name: string;
  window: MetricsWindow;
}) {
  const query = usePromptMetrics(name, window);

  return (
    <div>
      <h2 className="text-lg font-semibold">Observability</h2>

      <QueryState
        query={query}
        label="metrics"
        isEmpty={(d) => d.overall.request_count === 0}
        empty={
          <p className="text-muted-foreground mt-6 text-sm">
            No executions recorded in this window. Run this prompt in the playground to start
            collecting metrics.
          </p>
        }
      >
        {(data) => (
          <div className="mt-4 space-y-6">
            <p className="text-muted-foreground text-xs" title={new Date(data.since).toLocaleString()}>
              since {formatRelative(data.since)}
            </p>
            <OverallStats data={data} />
            <Trends
              name={name}
              window={window}
              versions={data.by_version.map((v) => v.version_number).sort((a, b) => b - a)}
            />
            <div className="grid gap-4 lg:grid-cols-2">
              <ByVersion data={data} name={name} window={window} />
              <CostBySource data={data} />
            </div>
          </div>
        )}
      </QueryState>
    </div>
  );
}
