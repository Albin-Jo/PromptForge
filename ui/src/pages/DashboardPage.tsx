import { Link, useParams, useSearchParams } from "react-router-dom";
import { History, LineChart, Play, ShieldCheck } from "lucide-react";
import { DashboardHeader } from "../components/DashboardHeader";
import { PromptTabs } from "../components/PromptTabs";
import { AlertsPanel } from "../components/AlertsPanel";
import { ObservabilityPanel } from "../components/ObservabilityPanel";
import { EvalPanel } from "../components/EvalPanel";
import { ScanPanel } from "../components/ScanPanel";
import { VersionComparison } from "../components/VersionComparison";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Skeleton } from "../components/ui/skeleton";
import { usePromptMetrics } from "../lib/metrics/api";
import { usePrompt } from "../lib/prompts/api";
import type { MetricsWindow } from "../lib/metrics/types";

// Anchor target id for the on-page Eval section (the action row scrolls here).
const EVAL_ANCHOR = "eval";

// Sprint 21 T1 (option b, ADR 0025): the dashboard is the per-prompt gateway, so it carries a
// prominent "Latest version: vN" action row that puts Playground / Scan / Eval one click away
// without opening the Versions table. Playground and Scan are version-scoped, so they link to the
// latest version explicitly (the version is visible in the row); Eval is a panel on this same page,
// so it scrolls to it rather than navigating.
function LatestVersionActions({ name, latest }: { name: string; latest: number }) {
  const base = encodeURIComponent(name);
  return (
    <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-sm">
        <span className="text-muted-foreground">Latest version</span>{" "}
        <span className="font-medium text-foreground">v{latest}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm" variant="outline">
          <Link to={`/prompts/${base}/versions/${latest}/playground`}>
            <Play /> Playground
          </Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to={`/prompts/${base}/versions/${latest}/scan`}>
            <ShieldCheck /> Scan
          </Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to={`/prompts/${base}/versions/${latest}/runs`}>
            <History /> Runs
          </Link>
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            document
              .getElementById(EVAL_ANCHOR)
              ?.scrollIntoView({ behavior: "smooth", block: "start" })
          }
        >
          <LineChart /> Eval
        </Button>
      </div>
    </Card>
  );
}

// One coherent loading state for the whole dashboard body — reserves the shape of the panels so the
// page doesn't reflow block-by-block as each panel's query resolves. Mirrors the panel layout below.
function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-20" />
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      </div>
      <Skeleton className="h-48" />
      <Skeleton className="h-32" />
      <Skeleton className="h-64" />
    </div>
  );
}

// The per-prompt dashboard: observability, eval scores, security, and a version comparison. The
// metrics window lives here so every panel shares it (the header owns the single visible toggle, so
// changing it drives every panel below — eval quality is reported within the same window). The core
// metrics query is read here too (shared cache) to gate the body on one unified skeleton.
export function DashboardPage() {
  const { name } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("window");
  const window: MetricsWindow = raw === "24h" || raw === "30d" ? raw : "7d";
  const setWindow = (w: MetricsWindow) => setSearchParams({ window: w }, { replace: true });
  const metrics = usePromptMetrics(name, window);
  // The prompt (not metrics) is the system of record for versions — a version with no traces
  // yet won't appear in metrics but is still the latest we can play with / scan.
  const prompt = usePrompt(name);

  if (!name) return null;

  const versions = prompt.data?.versions ?? [];
  const latest = versions.length
    ? Math.max(...versions.map((v) => v.version_number))
    : null;

  return (
    <div className="space-y-6">
      <DashboardHeader name={name} window={window} onWindowChange={setWindow} />
      <PromptTabs name={name} />
      {latest !== null && <LatestVersionActions name={name} latest={latest} />}
      {metrics.isPending ? (
        <DashboardSkeleton />
      ) : (
        <>
          <AlertsPanel name={name} window={window} />
          <ObservabilityPanel name={name} window={window} />
          {/* scroll-mt clears the sticky top bar when the action row scrolls here. */}
          <div id={EVAL_ANCHOR} className="scroll-mt-20">
            <EvalPanel name={name} window={window} />
          </div>
          <ScanPanel name={name} />
          <VersionComparison name={name} window={window} />
        </>
      )}
    </div>
  );
}
