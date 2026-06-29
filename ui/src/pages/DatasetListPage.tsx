import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Database, Trash2 } from "lucide-react";
import { useDatasets } from "../lib/datasets/api";
import { useCan } from "../lib/auth/AuthContext";
import { QueryState } from "../components/QueryState";
import { EmptyState } from "../components/EmptyState";
import { DeleteDatasetDialog } from "../components/DeleteDatasetDialog";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";

export function DatasetListPage() {
  const query = useDatasets();
  const navigate = useNavigate();
  const canEdit = useCan("editor");
  // The set queued for deletion (drives the confirm dialog); null when closed.
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Golden sets</h1>
        {canEdit && (
          <Button asChild>
            <Link to="/datasets/new">New golden set</Link>
          </Button>
        )}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        A golden set is the curated test cases a prompt must pass before promotion — its quality
        gate. Attach one from a prompt's editor.
      </p>

      <div className="mt-6">
        <QueryState
          query={query}
          label="golden sets"
          isEmpty={(datasets) => datasets.length === 0}
          empty={
            <EmptyState
              icon={Database}
              title="No golden sets yet"
              description="Create one to gate a prompt's promotions on quality."
              action={
                canEdit
                  ? { label: "New golden set", onClick: () => navigate("/datasets/new") }
                  : undefined
              }
            />
          }
        >
          {(datasets) => (
            <Card className="py-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-right">Cases</TableHead>
                    <TableHead>Description</TableHead>
                    {canEdit && (
                      <TableHead className="w-0">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datasets.map((d) => (
                    <TableRow key={d.name}>
                      <TableCell>
                        <Link
                          to={`/datasets/${encodeURIComponent(d.name)}/edit`}
                          className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          {d.name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-right">
                        {d.item_count}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {d.description ?? "—"}
                      </TableCell>
                      {canEdit && (
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setPendingDelete(d.name)}
                            aria-label={`Delete ${d.name}`}
                          >
                            <Trash2 className="size-4" aria-hidden />
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </QueryState>
      </div>

      <DeleteDatasetDialog
        dataset={pendingDelete}
        onOpenChange={(open) => !open && setPendingDelete(null)}
      />
    </div>
  );
}
