import { CheckCircle2, TriangleAlert } from "lucide-react";

import { usePromptAlerts } from "../lib/alerts/api";
import { alertMeta, formatAlertScope } from "../lib/alerts/presentation";
import type { Alert } from "../lib/alerts/types";
import type { MetricsWindow } from "../lib/metrics/types";
import { InfoHint } from "./InfoHint";
import { QueryState } from "./QueryState";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

// One firing alert: its severity badge, where it fired (prompt-wide / a version), and the API's
// human message. We lean on `message` for the numbers — it already carries the right units.
function AlertRow({ alert }: { alert: Alert }) {
  const meta = alertMeta(alert.kind);
  return (
    <li className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Badge variant={meta.variant}>{meta.label}</Badge>
          <span className="text-muted-foreground text-xs">{formatAlertScope(alert.scope)}</span>
        </div>
        <p className="text-foreground mt-1 text-sm">{alert.message}</p>
      </div>
    </li>
  );
}

// Healthy: no breach in the selected window. The good case, shown plainly (mirrors Needs attention).
function AlertsEmpty() {
  return (
    <Card className="mt-4">
      <CardContent className="py-6">
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <CheckCircle2 className="size-4 text-success" /> No drift detected — this prompt is
          within its thresholds for the selected window.
        </p>
      </CardContent>
    </Card>
  );
}

function AlertsList({ alerts }: { alerts: Alert[] }) {
  // Most-urgent first; stable tiebreak on scope so the order doesn't jitter between fetches.
  const sorted = [...alerts].sort(
    (a, b) => alertMeta(b.kind).severity - alertMeta(a.kind).severity || a.scope.localeCompare(b.scope),
  );
  return (
    <Card className="mt-4 border-destructive/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TriangleAlert className="size-4 text-destructive" />
          {sorted.length} active alert{sorted.length === 1 ? "" : "s"}
        </CardTitle>
        <CardDescription>Thresholds breached in this window — investigate below.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-border divide-y">
          {sorted.map((a) => (
            <AlertRow key={`${a.kind}:${a.scope}`} alert={a} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// The per-prompt drift-alerts surface (Sprint 16g). Reached from the Overview "Needs attention"
// tile via the prompt dashboard. Shares the dashboard's window so the alerts match what's on screen.
export function AlertsPanel({ name, window }: { name: string; window: MetricsWindow }) {
  const query = usePromptAlerts(name, window);

  return (
    <section id="alerts">
      <h2 className="flex items-center gap-1.5 text-lg font-semibold">
        Drift alerts
        <InfoHint text="An alert fires when this prompt breaches a threshold in the selected window — a high error rate, a quality regression, quality below its floor, or cost per request too high." />
      </h2>
      <p className="text-muted-foreground mt-1 text-sm">
        Drift and regression breaches over the selected window.
      </p>
      <QueryState
        query={query}
        label="alerts"
        isEmpty={(d) => d.alerts.length === 0}
        empty={<AlertsEmpty />}
      >
        {(data) => <AlertsList alerts={data.alerts} />}
      </QueryState>
    </section>
  );
}
