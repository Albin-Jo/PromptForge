import { useQueryClient } from "@tanstack/react-query";

import { MetricsWindowToggle } from "./MetricsWindowToggle";
import { PromoteDialog } from "./PromoteDialog";
import { FreshnessIndicator } from "./FreshnessIndicator";
import { Badge } from "./ui/badge";
import { useCan } from "../lib/auth/AuthContext";
import { usePrompt, useResolveLabel } from "../lib/prompts/api";
import { labelVariant } from "../lib/prompts/labels";
import { usePromptMetrics } from "../lib/metrics/api";
import type { MetricsWindow } from "../lib/metrics/types";

// The labels we resolve to "what's live" badges, in headline order. Mirrors PromoteDialog's
// PROMOTABLE_LABELS.
const LIVE_LABELS = ["production", "staging"];

// "What's serving traffic right now" — the dashboard's missing anchor (a label move *is* a
// deployment). Each badge names the version the pointer resolves to; an unset label renders nothing.
function LiveLabelBadges({ name }: { name: string }) {
  const production = useResolveLabel(name, "production");
  const staging = useResolveLabel(name, "staging");
  const dataByLabel: Record<string, { version_number: number } | null | undefined> = {
    production: production.data,
    staging: staging.data,
  };
  const resolved = LIVE_LABELS.filter((label) => dataByLabel[label]);

  if (resolved.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {resolved.map((label) => (
        <Badge key={label} variant={labelVariant(label)}>
          {label} · v{dataByLabel[label]!.version_number}
        </Badge>
      ))}
    </div>
  );
}

// The per-prompt dashboard header: title, the live label pointers, a Promote action (admin) on the
// latest version, the shared window toggle, and a freshness indicator. Owning the toggle here (not
// buried inside the Observability panel) means one visible control drives every panel below it.
export function DashboardHeader({
  name,
  window,
  onWindowChange,
}: {
  name: string;
  window: MetricsWindow;
  onWindowChange: (w: MetricsWindow) => void;
}) {
  const prompt = usePrompt(name);
  const canPromote = useCan("admin");
  // Shares the ObservabilityPanel's cache entry (same key) — reads freshness without a second fetch.
  const metrics = usePromptMetrics(name, window);
  const queryClient = useQueryClient();

  const latest = (prompt.data?.versions ?? []).reduce(
    (max, v) => Math.max(max, v.version_number),
    0,
  );

  // Refresh *every* query that carries this prompt's name (metrics, timeseries, alerts, labels,
  // scans, detail) — not just the core metrics call — so the whole dashboard updates as a unit. The
  // freshness chip still reads the metrics query's state below.
  function refreshAll() {
    void queryClient.invalidateQueries({
      predicate: (q) => Array.isArray(q.queryKey) && (q.queryKey as unknown[]).includes(name),
    });
  }

  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
        <p className="text-muted-foreground mt-1 text-sm">Health, traffic, evals, and versions.</p>
        <LiveLabelBadges name={name} />
      </div>
      <div className="flex flex-col items-end gap-2">
        <div className="flex items-center gap-2">
          {latest > 0 && (
            <PromoteDialog name={name} versionNumber={latest} canPromote={canPromote} />
          )}
          <MetricsWindowToggle value={window} onChange={onWindowChange} />
        </div>
        <FreshnessIndicator
          updatedAt={metrics.dataUpdatedAt}
          isFetching={metrics.isFetching}
          onRefresh={refreshAll}
        />
      </div>
    </div>
  );
}
