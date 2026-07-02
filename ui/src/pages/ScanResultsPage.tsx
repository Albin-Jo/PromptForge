import { useParams } from "react-router-dom";
import { isScanRunning, useTriggerScan, useVersionScan } from "../lib/scans/api";
import type { Severity, VersionScanStatus } from "../lib/scans/types";
import { useCan } from "../lib/auth/AuthContext";
import { toast, toastError } from "../lib/toast";
import { FindingsByCategory } from "../components/ScanFindingsView";
import { QueryState } from "../components/QueryState";
import { RunActionButton } from "../components/RunActionButton";
import { SeverityBadge } from "../components/SeverityBadge";
import { Badge } from "../components/ui/badge";

// The status-specific body once the scan record has loaded. The scan lifecycle lives *inside* a
// successful response, so we branch on it here (not in QueryState).
function ScanBody({ data }: { data: VersionScanStatus }) {
  if (data.status === "unscanned") {
    return <p className="mt-6 text-sm text-muted-foreground">This version hasn't been scanned yet.</p>;
  }
  if (data.status === "pending" || data.status === "running") {
    return (
      <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Badge variant="warning">In progress</Badge> Scan in progress…
      </p>
    );
  }
  if (data.status === "failed") {
    return (
      <p className="mt-6 text-sm text-destructive">The scan errored — check the worker logs.</p>
    );
  }

  const findings = data.findings ?? [];
  if (findings.length === 0) {
    return (
      <div className="mt-6 flex items-center gap-3">
        <SeverityBadge severity="none" />
        <span className="text-sm text-muted-foreground">Clean — no security findings.</span>
      </div>
    );
  }

  return (
    <>
      <div className="mt-6 flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Risk level</span>
        <SeverityBadge severity={(data.risk_level as Severity | "none") ?? "none"} />
        <span className="text-sm text-muted-foreground">
          · {findings.length} finding{findings.length === 1 ? "" : "s"}
        </span>
      </div>
      <FindingsByCategory findings={findings} />
    </>
  );
}

export function ScanResultsPage() {
  const { name, versionNumber } = useParams();
  const version = versionNumber !== undefined ? Number(versionNumber) : undefined;
  // Poll so a triggered scan is watched to completion (stops at completed/failed).
  const query = useVersionScan(name, version, { poll: true });

  // On-demand scan is editor+. In flight while the trigger is pending or the polled scan is running.
  const canRun = useCan("editor");
  const triggerScan = useTriggerScan(name ?? "");
  const running =
    triggerScan.isPending || (query.data ? isScanRunning(query.data.status) : false);

  function runScan() {
    // The route guarantees both, but guard so we never POST to a malformed `/prompts//versions/…`.
    if (!name || version === undefined) return;
    triggerScan.mutate(version, {
      onSuccess: () => toast.success(`Started scan for v${version}`),
      onError: (err) => toastError(err, "Could not start the scan."),
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          {name} — v{versionNumber} security scan
        </h1>
        {/* Navigation back to versions is the breadcrumb's job now (the prompt-name crumb
            links to .../versions); the header keeps only the page action. */}
        <RunActionButton
          onRun={runScan}
          running={running}
          canRun={canRun}
          idleLabel="Run scan"
          runningLabel="Scanning…"
          deniedReason="Requires the editor role"
        />
      </div>

      <QueryState query={query} label="scan results">
        {(data) => <ScanBody data={data} />}
      </QueryState>
    </div>
  );
}
