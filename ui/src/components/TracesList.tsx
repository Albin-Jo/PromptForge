// The trace list for one prompt (Sprint 24, T3): every execution, newest first, filterable by
// version and paged (the traces table is the fastest-growing one). Each row is selectable — the
// parent opens the drill-down (T4) for the chosen execution. The list is lean: latency, cost,
// status, model, time — never the rendered prompt/output, which load only on the drill-down.

import { useState } from "react";
import { TRACE_PAGE_SIZE, useTraces } from "../lib/traces/api";
import type { TraceSummary } from "../lib/traces/types";
import { formatCost, formatMs, formatRelative } from "../lib/metrics/format";
import { QueryState } from "./QueryState";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";

const ALL_VERSIONS = "all";

function StatusBadge({ status }: { status: TraceSummary["status"] }) {
  return (
    <Badge variant={status === "ok" ? "success" : "destructive"}>
      {status === "ok" ? "OK" : "Error"}
    </Badge>
  );
}

function TraceRow({
  trace,
  selected,
  onSelect,
}: {
  trace: TraceSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <TableRow
      role="button"
      tabIndex={0}
      aria-expanded={selected}
      onClick={() => onSelect(trace.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(trace.id);
        }
      }}
      className={`cursor-pointer ${selected ? "bg-muted/50" : ""}`}
    >
      <TableCell
        className="font-medium text-foreground"
        title={new Date(trace.created_at).toLocaleString()}
      >
        {formatRelative(trace.created_at)}
      </TableCell>
      <TableCell className="text-muted-foreground">{trace.model}</TableCell>
      <TableCell>
        <StatusBadge status={trace.status} />
      </TableCell>
      <TableCell className="text-right text-muted-foreground tabular-nums">
        {formatMs(trace.latency_ms)}
      </TableCell>
      <TableCell className="text-right text-muted-foreground tabular-nums">
        {formatCost(trace.cost_usd)}
      </TableCell>
    </TableRow>
  );
}

export function TracesList({
  name,
  versions,
  selectedId,
  onSelect,
}: {
  name: string | undefined;
  versions: number[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
}) {
  const [version, setVersion] = useState<string>(ALL_VERSIONS);
  const [offset, setOffset] = useState(0);
  const versionFilter = version === ALL_VERSIONS ? undefined : Number(version);
  const query = useTraces(name, versionFilter, offset);

  function changeVersion(value: string) {
    setVersion(value);
    setOffset(0); // a new filter starts at the first page
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">Traces</CardTitle>
            <CardDescription>Recent executions, newest first.</CardDescription>
          </div>
          {versions.length > 0 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Version</span>
              <Select value={version} onValueChange={changeVersion}>
                <SelectTrigger className="w-32" aria-label="Filter traces by version">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VERSIONS}>All versions</SelectItem>
                  {versions.map((v) => (
                    <SelectItem key={v} value={String(v)}>
                      v{v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <QueryState
          query={query}
          label="traces"
          isEmpty={(traces) => traces.length === 0 && offset === 0}
          empty={
            <p className="text-sm text-muted-foreground">
              No executions recorded for this prompt yet.
            </p>
          }
        >
          {(traces) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Latency</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {traces.map((trace) => (
                    <TraceRow
                      key={trace.id}
                      trace={trace}
                      selected={trace.id === selectedId}
                      onSelect={onSelect}
                    />
                  ))}
                </TableBody>
              </Table>
              <div className="mt-4 flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - TRACE_PAGE_SIZE))}
                >
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">
                  {offset + 1}–{offset + traces.length}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  // A short page means there are no more rows to fetch.
                  disabled={traces.length < TRACE_PAGE_SIZE}
                  onClick={() => setOffset((o) => o + TRACE_PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}
