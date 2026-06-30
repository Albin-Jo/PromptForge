import { CheckCircle2, TriangleAlert, X } from "lucide-react";
import { useCallback, useState } from "react";

import { useAlertPolicy, usePromptAlerts } from "../lib/alerts/api";
import { alertMeta, formatAlertScope, formatThreshold } from "../lib/alerts/presentation";
import type { Alert, AlertThreshold } from "../lib/alerts/types";
import type { MetricsWindow } from "../lib/metrics/types";
import { InfoHint } from "./InfoHint";
import { QueryState } from "./QueryState";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

// --- dismiss persistence -------------------------------------------------

type DismissEntry = { observed: number; threshold: number };
type DismissMap = Record<string, DismissEntry>;

const STORAGE_KEY = "pf-dismissed-alerts";

function loadDismissMap(): DismissMap {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function saveDismissMap(map: DismissMap): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
}

function alertKey(name: string, alert: Alert): string {
  return `${name}:${alert.kind}:${alert.scope}`;
}

// A dismissal is live only while observed+threshold are unchanged — if the breach shifts
// the alert reappears automatically without the user needing to clear anything.
function isDismissed(map: DismissMap, name: string, alert: Alert): boolean {
  const entry = map[alertKey(name, alert)];
  return entry?.observed === alert.observed && entry?.threshold === alert.threshold;
}

function useDismissedAlerts(name: string) {
  const [map, setMap] = useState<DismissMap>(loadDismissMap);

  const dismiss = useCallback(
    (alert: Alert) => {
      const next = {
        ...map,
        [alertKey(name, alert)]: { observed: alert.observed, threshold: alert.threshold },
      };
      saveDismissMap(next);
      setMap(next);
    },
    [map, name],
  );

  const check = useCallback(
    (alert: Alert) => isDismissed(map, name, alert),
    [map, name],
  );

  return { check, dismiss };
}

// --- components ---------------------------------------------------------

function AlertRow({ alert, onDismiss }: { alert: Alert; onDismiss: (a: Alert) => void }) {
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
      <Button
        variant="ghost"
        size="sm"
        className="text-muted-foreground hover:text-foreground shrink-0"
        onClick={() => onDismiss(alert)}
        aria-label="Acknowledge alert"
      >
        <X className="size-4" />
      </Button>
    </li>
  );
}

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

function AlertsList({
  alerts,
  name,
}: {
  alerts: Alert[];
  name: string;
}) {
  const { check, dismiss } = useDismissedAlerts(name);

  const visible = alerts.filter((a) => !check(a));
  const hiddenCount = alerts.length - visible.length;

  const sorted = [...visible].sort(
    (a, b) => alertMeta(b.kind).severity - alertMeta(a.kind).severity || a.scope.localeCompare(b.scope),
  );

  if (sorted.length === 0 && hiddenCount > 0) {
    return (
      <Card className="mt-4">
        <CardContent className="py-6">
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <CheckCircle2 className="size-4 text-success" />
            {hiddenCount} acknowledged alert{hiddenCount === 1 ? "" : "s"} — will reappear if the
            breach changes.
          </p>
        </CardContent>
      </Card>
    );
  }

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
            <AlertRow key={`${a.kind}:${a.scope}`} alert={a} onDismiss={dismiss} />
          ))}
        </ul>
        {hiddenCount > 0 && (
          <p className="text-muted-foreground mt-3 text-xs">
            {hiddenCount} acknowledged alert{hiddenCount === 1 ? "" : "s"} hidden — reappears if
            the breach changes.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// The active numeric thresholds the alerts above are judged against (Sprint 29). Always visible — so
// a user sees *why* an alert did or didn't fire, including in the healthy state. Supplementary, so a
// pending or failed policy fetch simply renders nothing rather than disturbing the panel.
function ThresholdsLine({ thresholds }: { thresholds: AlertThreshold[] }) {
  return (
    <p className="text-muted-foreground mt-2 text-xs">
      <span className="text-foreground/80 font-medium">Thresholds:</span>{" "}
      {thresholds.map((t) => `${t.label} ${formatThreshold(t)}`).join(" · ")}
    </p>
  );
}

// The per-prompt drift-alerts surface (Sprint 16g). Reached from the Overview "Needs attention"
// tile via the prompt dashboard. Shares the dashboard's window so the alerts match what's on screen.
export function AlertsPanel({ name, window }: { name: string; window: MetricsWindow }) {
  const query = usePromptAlerts(name, window);
  const policy = useAlertPolicy();

  return (
    <section id="alerts">
      <h2 className="flex items-center gap-1.5 text-lg font-semibold">
        Drift alerts
        <InfoHint text="An alert fires when this prompt breaches a threshold in the selected window — a high error rate, a quality regression, quality below its floor, or cost per request too high." />
      </h2>
      <p className="text-muted-foreground mt-1 text-sm">
        Drift and regression breaches over the selected window.
      </p>
      {policy.data && policy.data.thresholds.length > 0 && (
        <ThresholdsLine thresholds={policy.data.thresholds} />
      )}
      <QueryState
        query={query}
        label="alerts"
        isEmpty={(d) => d.alerts.length === 0}
        empty={<AlertsEmpty />}
      >
        {(data) => <AlertsList alerts={data.alerts} name={name} />}
      </QueryState>
    </section>
  );
}
