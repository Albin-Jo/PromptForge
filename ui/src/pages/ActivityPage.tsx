import { ClipboardList } from "lucide-react";

import { useAuditEvents } from "../lib/audit/api";
import { EmptyState } from "../components/EmptyState";
import { QueryState } from "../components/QueryState";
import { Card } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";

// Admin-only audit log surface. Route is gated by RequireAdmin; nav entry filtered by adminOnly.
// Targets GET /audit-log — shows an error state if the backend hasn't exposed it yet.
export function ActivityPage() {
  const query = useAuditEvents();

  return (
    <div>
      <h1 className="text-xl font-semibold">Activity</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        All audited actions — who did what, and when.
      </p>

      <div className="mt-6">
        <QueryState
          query={query}
          label="activity"
          isEmpty={(d) => d.events.length === 0}
          empty={
            <EmptyState
              icon={ClipboardList}
              title="No activity yet"
              description="Audited actions (promotions, user changes, config edits) will appear here."
            />
          }
        >
          {(data) => (
            <Card className="py-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead>When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.events.map((event) => (
                    <TableRow key={event.id}>
                      <TableCell className="font-medium">{event.actor}</TableCell>
                      <TableCell className="text-muted-foreground">{event.action}</TableCell>
                      <TableCell className="text-muted-foreground">{event.target}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(event.timestamp).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </QueryState>
      </div>
    </div>
  );
}
