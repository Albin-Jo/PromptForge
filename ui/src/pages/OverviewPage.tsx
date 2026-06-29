import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronsUpDown, CheckCircle2, Download, FileWarning } from "lucide-react";

import { FreshnessIndicator } from "@/components/FreshnessIndicator";
import { InfoHint } from "@/components/InfoHint";
import { MetricsWindowToggle } from "@/components/MetricsWindowToggle";
import { QueryState } from "@/components/QueryState";
import { Sparkline } from "@/components/charts/Sparkline";
import { TrendChart } from "@/components/charts/TrendChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatCost, formatMs, formatPct, formatQuality } from "@/lib/metrics/format";
import { bucketsToTrend, formatBucketLabel, formatBucketTick } from "@/lib/metrics/timeseries";
import type { MetricsWindow } from "@/lib/metrics/types";
import { useOverview } from "@/lib/overview/api";
import { ATTENTION_META, ATTENTION_ORDER, attentionWeight } from "@/lib/overview/attention";
import { sortPrompts } from "@/lib/overview/sort";
import type { SortDir, SortKey } from "@/lib/overview/sort";
import type { FleetOverview, PromptRollup } from "@/lib/overview/types";
import { usePrompts } from "@/lib/prompts/api";
import type { PromptSummary } from "@/lib/prompts/types";

// Error rate above this reads as unhealthy — mirrors the API's high_error_rate attention rule, so
// the headline colour and the per-prompt flag agree on what "bad" means.
const ERROR_RATE_THRESHOLD = 0.05;

// One fleet stat with a glance-level sparkline of the same metric over the window.
function StatCard({
  label,
  value,
  series,
  color,
}: {
  label: string;
  value: string;
  series: (number | null)[];
  color: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <Sparkline data={series} color={color} height={36} aria-label={`${label} trend`} className="w-full" />
      </CardContent>
    </Card>
  );
}

function TrendCard({
  title,
  description,
  data,
  interval,
  seriesKey,
  seriesLabel,
  color,
  valueFormatter,
  empty = false,
}: {
  title: string;
  description: string;
  data: ReturnType<typeof bucketsToTrend>;
  interval: FleetOverview["interval"];
  seriesKey: string;
  seriesLabel: string;
  color: string;
  valueFormatter: (value: number | string | undefined) => string;
  empty?: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="text-muted-foreground py-6 text-sm">No traffic in this window.</p>
        ) : (
          <TrendChart
            data={data}
            xKey="bucket"
            variant="area"
            series={[{ key: seriesKey, label: seriesLabel, color }]}
            className="aspect-[3/1] w-full"
            xTickFormatter={(v) => formatBucketTick(v, interval)}
            tooltipLabelFormatter={(v) => formatBucketLabel(v, interval)}
            tooltipValueFormatter={(v) => valueFormatter(v)}
          />
        )}
      </CardContent>
    </Card>
  );
}

// The "prompts needing attention" list — rows sorted most-urgent first, each linking to its
// dashboard with a badge per fired rule. Empty = a healthy fleet (the good case, shown plainly).
function NeedsAttention({ prompts }: { prompts: PromptRollup[] }) {
  const flagged = prompts
    .filter((p) => p.attention.length > 0)
    .sort((a, b) => attentionWeight(b.attention) - attentionWeight(a.attention) || a.name.localeCompare(b.name));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="size-4" /> Needs attention
        </CardTitle>
        <CardDescription>
          Prompts tripping a health rule (errors, evals, scans, or gone quiet).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {flagged.length === 0 ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <CheckCircle2 className="size-4 text-success" /> Every prompt looks healthy in this
            window.
          </p>
        ) : (
          <ul aria-label="Needs attention" className="divide-border divide-y">
            {flagged.map((p) => (
              <li key={p.name} className="flex items-center justify-between gap-4 py-2.5">
                <div className="min-w-0">
                  {/* A flagged prompt links to its dashboard — the health/triage view (metrics,
                      evals, scans) is where you investigate why it's flagged, not the editor. */}
                  <Link
                    to={`/prompts/${encodeURIComponent(p.name)}/dashboard`}
                    className="hover:underline font-medium"
                  >
                    {p.name}
                  </Link>
                  <span className="text-muted-foreground ml-2 text-xs">
                    {p.latest_version !== null ? `v${p.latest_version}` : "no versions"}
                    {p.error_rate !== null && ` · ${formatPct(p.error_rate)} errors`}
                    {p.quality !== null && ` · quality ${formatQuality(p.quality)}`}
                  </span>
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                  {ATTENTION_ORDER.filter((r) => p.attention.includes(r)).map((r) => (
                    <Badge key={r} variant={ATTENTION_META[r].variant} title={ATTENTION_META[r].description}>
                      {ATTENTION_META[r].label}
                    </Badge>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// The full fleet inventory — every prompt, sortable on any column, exportable to CSV. This is the
// dashboard's "see everything ranked" surface (Needs attention is only the flagged subset). The sort
// itself lives in lib/overview/sort.ts (pure + tested).
function AllPrompts({ prompts, window }: { prompts: PromptRollup[]; window: MetricsWindow }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "request_count",
    dir: "desc",
  });

  const sorted = useMemo(() => sortPrompts(prompts, sort), [prompts, sort]);

  function toggle(key: SortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "name" ? "asc" : "desc" },
    );
  }

  function exportCsv() {
    const csv = toCsv(sorted, [
      { header: "prompt", value: (p) => p.name },
      { header: "latest_version", value: (p) => p.latest_version },
      { header: "requests", value: (p) => p.request_count },
      { header: "error_rate", value: (p) => p.error_rate },
      { header: "p95_ms", value: (p) => p.p95_ms },
      { header: "cost_usd", value: (p) => p.cost_usd },
      { header: "quality", value: (p) => p.quality },
      { header: "attention", value: (p) => p.attention.join("|") },
    ]);
    downloadCsv(`promptforge-fleet-${window}.csv`, csv);
  }

  const SortHeader = ({
    label,
    sortKey,
    align = "right",
    hint,
  }: {
    label: string;
    sortKey: SortKey;
    align?: "left" | "right";
    hint?: string;
  }) => {
    const active = sort.key === sortKey;
    const Icon = !active ? ChevronsUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
    return (
      <th className={align === "right" ? "py-2 text-right font-medium" : "py-2 font-medium"}>
        <button
          type="button"
          onClick={() => toggle(sortKey)}
          aria-label={`Sort by ${label}`}
          className={`hover:text-foreground inline-flex items-center gap-1 ${align === "right" ? "flex-row-reverse" : ""} ${active ? "text-foreground" : ""}`}
        >
          {label}
          <Icon className="size-3" />
        </button>
        {hint && <InfoHint text={hint} className="ml-1" />}
      </th>
    );
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">All prompts</CardTitle>
            <CardDescription>Every prompt in the fleet — click a column to sort.</CardDescription>
          </div>
          <Button variant="outline" size="sm" className="gap-2" onClick={exportCsv}>
            <Download className="size-3.5" /> Export CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table aria-label="All prompts" className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-muted-foreground border-border border-b text-left">
                <SortHeader label="Prompt" sortKey="name" align="left" />
                <SortHeader label="Requests" sortKey="request_count" />
                <SortHeader label="Error rate" sortKey="error_rate" />
                <SortHeader label="p95 (ms)" sortKey="p95_ms" />
                <SortHeader label="Cost (USD)" sortKey="cost_usd" />
                <SortHeader
                  label="Quality (0–1)"
                  sortKey="quality"
                  hint="Eval quality score from 0 to 1 — higher is better, 1.0 is perfect."
                />
                <th className="py-2 pl-4 font-medium">Health</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.name} className="border-border/60 border-b">
                  <td className="py-2 font-medium">
                    <Link
                      to={`/prompts/${encodeURIComponent(p.name)}/dashboard`}
                      className="hover:underline"
                    >
                      {p.name}
                    </Link>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {p.latest_version !== null ? `v${p.latest_version}` : "—"}
                    </span>
                  </td>
                  <td className="py-2 text-right tabular-nums">{p.request_count.toLocaleString()}</td>
                  <td className="py-2 text-right tabular-nums">{formatPct(p.error_rate)}</td>
                  <td className="py-2 text-right tabular-nums">{formatMs(p.p95_ms)}</td>
                  <td className="py-2 text-right tabular-nums">{formatCost(p.cost_usd)}</td>
                  <td className="py-2 text-right tabular-nums">{formatQuality(p.quality)}</td>
                  <td className="py-2 pl-4">
                    {p.attention.length === 0 ? (
                      <CheckCircle2 className="size-4 text-success" aria-label="healthy" />
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {ATTENTION_ORDER.filter((r) => p.attention.includes(r)).map((r) => (
                          <Badge
                            key={r}
                            variant={ATTENTION_META[r].variant}
                            title={ATTENTION_META[r].description}
                          >
                            {ATTENTION_META[r].label}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// A strip of the most recently touched prompts (registry recency — distinct from the metrics
// rollup, so it reads the cheap prompt list rather than bloating the overview payload).
function RecentActivity() {
  const query = usePrompts();
  const recent = [...(query.data ?? [])]
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 6);

  if (recent.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent activity</CardTitle>
        <CardDescription>The prompts you've touched most recently.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {recent.map((p: PromptSummary) => (
          // "Recently touched" is the same affordance as the prompt list, so it opens the editor
          // (the app-wide convention for a plain prompt-name click) — not the dashboard.
          <Link
            key={p.name}
            to={`/prompts/${encodeURIComponent(p.name)}/edit`}
            className="bg-muted/50 hover:bg-muted rounded-md border px-3 py-1.5 text-sm transition-colors"
          >
            <span className="font-medium">{p.name}</span>
            <span className="text-muted-foreground ml-2 text-xs">
              {new Date(p.updated_at).toLocaleDateString()}
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
      <Skeleton className="h-48" />
    </div>
  );
}

function EmptyFleet() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileWarning className="size-4" /> No prompts yet
        </CardTitle>
        <CardDescription>
          Create your first prompt to start collecting traffic, evals, and scans.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Link to="/prompts/new" className="text-primary text-sm font-medium hover:underline">
          New prompt →
        </Link>
      </CardContent>
    </Card>
  );
}

function OverviewBody({ data, window }: { data: FleetOverview; window: MetricsWindow }) {
  const trend = bucketsToTrend(data.trend);

  // Fleet quality has no totals field (quality is per-version), so we average the per-prompt rollups
  // that have an eval. Deliberately UNWEIGHTED — every evaluated prompt counts equally regardless of
  // traffic, so this reads as "how good are our prompts" (fleet health), not "how good is the median
  // request". The sparkline rides the per-bucket quality the trend already carries.
  const qualities = data.prompts.map((p) => p.quality).filter((q): q is number => q !== null);
  const fleetQuality = qualities.length
    ? qualities.reduce((sum, q) => sum + q, 0) / qualities.length
    : null;

  // Don't paint a healthy error rate alarm-red — only colour it destructive past the threshold.
  const errorUnhealthy = (data.totals.error_rate ?? 0) > ERROR_RATE_THRESHOLD;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Requests"
          value={data.totals.request_count.toLocaleString()}
          series={trend.map((r) => r.requests)}
          color="var(--chart-1)"
        />
        <StatCard
          label="Error rate"
          value={formatPct(data.totals.error_rate)}
          series={trend.map((r) => r.errorRate)}
          color={errorUnhealthy ? "var(--destructive)" : "var(--chart-2)"}
        />
        <StatCard
          label="Total cost"
          value={formatCost(data.totals.total_cost_usd)}
          series={trend.map((r) => r.cost)}
          color="var(--chart-5)"
        />
        <StatCard
          label="Quality"
          value={formatQuality(fleetQuality)}
          series={trend.map((r) => r.quality)}
          color="var(--chart-4)"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <TrendCard
          title="Traffic"
          description="Requests across all prompts over the window."
          data={trend}
          interval={data.interval}
          seriesKey="requests"
          seriesLabel="Requests"
          color="var(--chart-1)"
          valueFormatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v ?? "—"))}
          empty={data.totals.request_count === 0}
        />
        <TrendCard
          title="Cost"
          description="Spend across all prompts over the window."
          data={trend}
          interval={data.interval}
          seriesKey="cost"
          seriesLabel="Cost (USD)"
          color="var(--chart-5)"
          valueFormatter={(v) => (v == null ? "—" : formatCost(String(v)))}
          empty={data.totals.request_count === 0}
        />
      </div>

      <NeedsAttention prompts={data.prompts} />
      <AllPrompts prompts={data.prompts} window={window} />
      <RecentActivity />
    </div>
  );
}

// The fleet-level landing page (Sprint 16c): totals + trends, a "needs attention" list, the full
// sortable inventory, and a recent-activity strip. The index route — the prompt list lives under
// "Prompts".
export function OverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("window");
  const window: MetricsWindow = raw === "24h" || raw === "30d" ? raw : "7d";
  const setWindow = (w: MetricsWindow) => setSearchParams({ window: w }, { replace: true });
  const query = useOverview(window);
  const queryClient = useQueryClient();

  // Refresh both the overview payload and the recent-activity prompt list (two separate queries).
  function refreshAll() {
    void queryClient.invalidateQueries({
      predicate: (q) => {
        const root = Array.isArray(q.queryKey) ? q.queryKey[0] : undefined;
        return root === "overview" || root === "prompts";
      },
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            A fleet-level view of every prompt's health, traffic, and evals.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <MetricsWindowToggle value={window} onChange={setWindow} />
          <FreshnessIndicator
            updatedAt={query.dataUpdatedAt}
            isFetching={query.isFetching}
            onRefresh={refreshAll}
          />
        </div>
      </div>

      <QueryState
        query={query}
        label="overview"
        loading={<OverviewSkeleton />}
        isEmpty={(d) => d.prompts.length === 0}
        empty={<EmptyFleet />}
      >
        {(data) => <OverviewBody data={data} window={window} />}
      </QueryState>
    </div>
  );
}
