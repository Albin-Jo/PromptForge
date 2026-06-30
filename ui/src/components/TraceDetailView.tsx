// The trace drill-down (Sprint 24, T4): one execution in full — its metadata, the rendered prompt
// that was sent, and the model output that came back. This is the core debugging surface, so the
// prompt and output are copyable. Loads the full trace (incl. the heavy input/output text) on
// demand, separately from the lean list.

import type { ReactNode } from "react";
import { useTrace } from "../lib/traces/api";
import type { TraceDetail } from "../lib/traces/types";
import { formatCost, formatMs } from "../lib/metrics/format";
import { CopyButton } from "./CopyButton";
import { QueryState } from "./QueryState";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{value}</dd>
    </div>
  );
}

const DASH = "—";

function tokens(detail: TraceDetail): string {
  const { input_tokens: i, output_tokens: o, total_tokens: t } = detail;
  if (i === null && o === null && t === null) return DASH;
  return `${i ?? "?"} in · ${o ?? "?"} out · ${t ?? "?"} total`;
}

/** A copyable text block — the rendered prompt or the model output. */
function TextBlock({ title, text, copyLabel }: { title: string; text: string | null; copyLabel: string }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">{title}</CardTitle>
        {text && <CopyButton text={text} label={copyLabel} />}
      </CardHeader>
      <CardContent>
        {text ? (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs text-foreground">
            {text}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">Not captured for this execution.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Detail({ detail }: { detail: TraceDetail }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Execution</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat
              label="Status"
              value={
                <Badge variant={detail.status === "ok" ? "success" : "destructive"}>
                  {detail.status === "ok" ? "OK" : (detail.error_type ?? "Error")}
                </Badge>
              }
            />
            <Stat label="Model" value={detail.provider_model ?? detail.model} />
            <Stat label="Provider" value={detail.provider ?? DASH} />
            <Stat label="Latency" value={formatMs(detail.latency_ms)} />
            <Stat label="Cost" value={formatCost(detail.cost_usd)} />
            <Stat label="Tokens" value={tokens(detail)} />
            <Stat label="Source" value={detail.source ?? DASH} />
            <Stat label="When" value={new Date(detail.created_at).toLocaleString()} />
            <Stat
              label="Request id"
              value={detail.request_id ? <code className="text-xs">{detail.request_id}</code> : DASH}
            />
          </dl>
        </CardContent>
      </Card>

      <TextBlock title="Rendered prompt" text={detail.input} copyLabel="Copy prompt" />
      <TextBlock title="Model output" text={detail.output} copyLabel="Copy output" />
    </div>
  );
}

export function TraceDetailView({ traceId }: { traceId: string | undefined }) {
  const query = useTrace(traceId);

  if (!traceId) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          Select a trace to inspect its prompt and output.
        </CardContent>
      </Card>
    );
  }

  return (
    <QueryState query={query} label="trace">
      {(detail) => <Detail detail={detail} />}
    </QueryState>
  );
}
