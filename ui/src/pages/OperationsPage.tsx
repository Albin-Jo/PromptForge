import { ExternalLink, TriangleAlert } from "lucide-react";

import { QueryState } from "../components/QueryState";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { useQueueHealth } from "../lib/ops/api";
import type { QueueHealth } from "../lib/ops/types";

// Flower (the Celery operator dashboard) runs as its own compose service. Overridable per env;
// defaults to the compose port so a local stack's link just works.
const FLOWER_URL = import.meta.env.VITE_FLOWER_URL ?? "http://localhost:5555";

// A single headline count. A null value (worker inspection failed) renders as an em dash.
function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value ?? "—"}</p>
      </CardContent>
    </Card>
  );
}

function QueueHealthView({ health }: { health: QueueHealth }) {
  if (!health.available) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="text-muted-foreground flex items-center gap-2 py-6 text-sm">
          <TriangleAlert className="text-destructive size-4 shrink-0" />
          Broker unreachable — queue and worker metrics are unavailable right now. They return once
          the broker is reachable; meanwhile, Flower has the live detail.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Workers online" value={health.workers} />
        <Stat label="Active tasks" value={health.active} />
        <Stat label="Queued (backlog)" value={health.queued} />
      </div>
      {health.queues && health.queues.length > 0 && (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Queue</TableHead>
                <TableHead className="text-right">Backlog</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {health.queues.map((queue) => (
                <TableRow key={queue.name}>
                  <TableCell className="font-medium">{queue.name}</TableCell>
                  <TableCell className="text-right tabular-nums">{queue.depth}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

// Admin-only operations surface (Sprint 29): Celery queue depth + worker liveness, with a link out
// to Flower for deeper task history. The route is gated by RequireAdmin and the nav entry is hidden
// from non-admins, so a non-admin never reaches this page.
export function OperationsPage() {
  const query = useQueueHealth();

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Operations</h1>
        <Button asChild variant="outline" size="sm">
          <a href={FLOWER_URL} target="_blank" rel="noreferrer">
            Open Flower <ExternalLink />
          </a>
        </Button>
      </div>
      <p className="text-muted-foreground mt-1 text-sm">
        Celery queue depth and worker liveness for the async backbone — evals, scans, and trace
        ingest. Failure history lives in Flower.
      </p>

      <div className="mt-6">
        <QueryState query={query} label="queue health">
          {(health) => <QueueHealthView health={health} />}
        </QueryState>
      </div>
    </div>
  );
}
