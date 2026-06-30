// The security-scan run-history list for one prompt version (Sprint 24, T2): every persisted scan,
// newest first, with drill-in to that scan's findings. Mirrors EvalRunsList; the drill-in reuses
// FindingsByCategory so a historical scan's findings render exactly like the live scan page.

import { useState } from "react";
import { useVersionScans } from "../lib/scans/api";
import type { ScanRunSummary } from "../lib/scans/types";
import { formatRelative } from "../lib/metrics/format";
import { FindingsByCategory } from "./ScanFindingsView";
import { QueryState } from "./QueryState";
import { SeverityBadge } from "./SeverityBadge";
import { Badge } from "./ui/badge";
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

// In-progress / failed scans have no risk badge yet; show a lifecycle badge instead.
function ScanOutcome({ scan }: { scan: ScanRunSummary }) {
  if (scan.status === "pending" || scan.status === "running") {
    return <Badge variant="warning">In progress</Badge>;
  }
  if (scan.status === "failed") {
    return <Badge variant="destructive">Scan failed</Badge>;
  }
  return <SeverityBadge severity={scan.risk_level ?? "none"} />;
}

// What a completed scan's drill-in shows: the grouped findings, or a clean line when there are none.
function ScanDrillIn({ scan }: { scan: ScanRunSummary }) {
  if (scan.status !== "completed") {
    return (
      <p className="py-2 text-sm text-muted-foreground">
        {scan.status === "failed"
          ? "The scan errored — check the worker logs."
          : "Scan in progress…"}
      </p>
    );
  }
  const findings = scan.findings ?? [];
  if (findings.length === 0) {
    return (
      <div className="flex items-center gap-3 py-2">
        <SeverityBadge severity="none" />
        <span className="text-sm text-muted-foreground">Clean — no security findings.</span>
      </div>
    );
  }
  return <FindingsByCategory findings={findings} />;
}

function ScanRow({ scan }: { scan: ScanRunSummary }) {
  const [open, setOpen] = useState(false);
  const count = scan.findings?.length ?? 0;

  function toggle() {
    setOpen((v) => !v);
  }

  return (
    <>
      <TableRow
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        className="cursor-pointer"
      >
        <TableCell
          className="font-medium text-foreground"
          title={new Date(scan.created_at).toLocaleString()}
        >
          {formatRelative(scan.created_at)}
        </TableCell>
        <TableCell>
          <ScanOutcome scan={scan} />
        </TableCell>
        <TableCell className="text-right text-muted-foreground">
          {scan.status === "completed" ? count : "—"}
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={3} className="bg-muted/30">
            <ScanDrillIn scan={scan} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export function ScanRunsList({
  name,
  versionNumber,
}: {
  name: string | undefined;
  versionNumber: number | undefined;
}) {
  // Poll so a freshly triggered scan flips from in-progress to a risk level without a refresh.
  const query = useVersionScans(name, versionNumber, { poll: true });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Security scans</CardTitle>
        <CardDescription>Every scan for this version, newest first.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState
          query={query}
          label="security scans"
          isEmpty={(scans) => scans.length === 0}
          empty={
            <p className="text-sm text-muted-foreground">No scans have run for this version yet.</p>
          }
        >
          {(scans) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Scan</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead className="text-right">Findings</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scans.map((scan) => (
                  <ScanRow key={scan.id} scan={scan} />
                ))}
              </TableBody>
            </Table>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}
