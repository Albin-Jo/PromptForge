import { useState } from "react";
import { Link } from "react-router-dom";
import type { VariantProps } from "class-variance-authority";

import { isScanRunning, useTriggerScan, useVersionScan } from "../lib/scans/api";
import type { ScanStatus, Severity, VersionScanStatus } from "../lib/scans/types";
import { usePrompt } from "../lib/prompts/api";
import { useCan } from "../lib/auth/AuthContext";
import { toast, toastError } from "../lib/toast";
import { QueryState } from "./QueryState";
import { RunActionButton } from "./RunActionButton";
import { SeverityBadge } from "./SeverityBadge";
import { Badge, badgeVariants } from "./ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

const STATUS_LABEL: Record<ScanStatus, string> = {
  unscanned: "Not scanned yet",
  pending: "In progress",
  running: "In progress",
  completed: "Scanned",
  failed: "Scan failed",
};

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

// Colour per lifecycle state. pending/running use "warning" (yellow) so the in-progress state
// matches EvalPanel's badge — the two panels read as one system. "completed" never reaches this
// badge (that branch renders the risk SeverityBadge instead), but the map stays total for type
// exhaustiveness, mirroring EvalPanel.
const STATUS_VARIANT: Record<ScanStatus, BadgeVariant> = {
  unscanned: "secondary",
  pending: "warning",
  running: "warning",
  completed: "success",
  failed: "destructive",
};

// The compact scan summary for one version: lifecycle state, risk level, finding count, and a link
// to the full findings page. The dashboard answers "is the live version safe?" at a glance; the
// per-finding detail stays on /scan so we don't duplicate it here.
function ScanSummary({ name, data }: { name: string; data: VersionScanStatus }) {
  if (data.status !== "completed") {
    return (
      <div className="flex items-center gap-3">
        <Badge variant={STATUS_VARIANT[data.status]}>{STATUS_LABEL[data.status]}</Badge>
        {data.status === "unscanned" && (
          <span className="text-muted-foreground text-sm">
            Run a scan to check this version for injection, secrets, PII, and jailbreaks.
          </span>
        )}
        {data.status === "failed" && (
          <span className="text-muted-foreground text-sm">
            The scan errored — check the worker logs.
          </span>
        )}
      </div>
    );
  }

  const findings = data.findings ?? [];
  const risk = (data.risk_level as Severity | "none") ?? "none";
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-muted-foreground text-sm">Risk level</span>
      <SeverityBadge severity={risk} />
      <span className="text-muted-foreground text-sm">
        · {findings.length} finding{findings.length === 1 ? "" : "s"}
      </span>
      {findings.length > 0 && (
        <Link
          to={`/prompts/${encodeURIComponent(name)}/versions/${data.version_number}/scan`}
          className="text-primary text-sm font-medium hover:underline"
        >
          View findings →
        </Link>
      )}
    </div>
  );
}

function ScanBody({ name, versions }: { name: string; versions: number[] }) {
  // Newest-first; default to the latest version (the one most likely about to be promoted).
  const ordered = [...versions].sort((a, b) => b - a);
  const [selected, setSelected] = useState<number>(ordered[0]);
  const scanQuery = useVersionScan(name, selected, { poll: true });

  const canRun = useCan("editor");
  const triggerScan = useTriggerScan(name);
  const running =
    triggerScan.isPending || (scanQuery.data ? isScanRunning(scanQuery.data.status) : false);

  function runScan() {
    triggerScan.mutate(selected, {
      onSuccess: () => toast.success(`Started scan for v${selected}`),
      onError: (err) => toastError(err, "Could not start the scan."),
    });
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">Security scan</CardTitle>
            <CardDescription>Injection, secret, PII, and jailbreak findings for a version.</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Version</span>
              <Select value={String(selected)} onValueChange={(v) => setSelected(Number(v))}>
                <SelectTrigger className="w-24" aria-label="Scan version">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ordered.map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      v{n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <RunActionButton
              onRun={runScan}
              running={running}
              canRun={canRun}
              idleLabel="Run scan"
              runningLabel="Scanning…"
              deniedReason="Requires the editor role"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <QueryState query={scanQuery} label="scan">
          {(data) => <ScanSummary name={name} data={data} />}
        </QueryState>
      </CardContent>
    </Card>
  );
}

// The scan surface on the per-prompt dashboard (closes the triage loop: the Overview "Scan" flag
// links here). Lists the prompt's versions, defaults to the latest, and shows its risk at a glance.
export function ScanPanel({ name }: { name: string }) {
  const query = usePrompt(name);

  return (
    <section id="scan">
      <h2 className="text-lg font-semibold">Security</h2>
      <p className="text-muted-foreground mt-1 text-sm">
        On-demand security scan for a selected version.
      </p>
      <div className="mt-4">
        <QueryState
          query={query}
          label="prompt"
          isEmpty={(d) => d.versions.length === 0}
          empty={<p className="text-muted-foreground text-sm">No versions to scan yet.</p>}
        >
          {(data) => (
            <ScanBody name={name} versions={data.versions.map((v) => v.version_number)} />
          )}
        </QueryState>
      </div>
    </section>
  );
}
