import { Link, useNavigate } from "react-router-dom";
import { Blocks } from "lucide-react";
import { useBlocks } from "../lib/blocks/api";
import type { Block } from "../lib/blocks/types";
import { useCan } from "../lib/auth/AuthContext";
import { QueryState } from "../components/QueryState";
import { EmptyState } from "../components/EmptyState";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";

function latestVersion(block: Block): number {
  return block.versions.reduce((max, v) => Math.max(max, v.version_number), 0);
}

export function BlockListPage() {
  const query = useBlocks();
  const navigate = useNavigate();
  const canEdit = useCan("editor");

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Blocks</h1>
        {canEdit && (
          <Button asChild>
            <Link to="/blocks/new">New block</Link>
          </Button>
        )}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Reusable, versioned fragments that prompts compose from.
      </p>

      <div className="mt-6">
        <QueryState
          query={query}
          label="blocks"
          isEmpty={(blocks) => blocks.length === 0}
          empty={
            <EmptyState
              icon={Blocks}
              title="No blocks yet"
              description="Create a block to reuse it across prompts via composition."
              action={
                canEdit ? { label: "New block", onClick: () => navigate("/blocks/new") } : undefined
              }
            />
          }
        >
          {(blocks) => (
            <Card className="py-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead className="text-right">Latest</TableHead>
                    <TableHead className="text-right">Versions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {blocks.map((b) => (
                    <TableRow key={b.name}>
                      <TableCell>
                        <Link
                          to={`/blocks/${encodeURIComponent(b.name)}`}
                          className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          {b.name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{b.role}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-right">
                        {latestVersion(b)}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-right">
                        {b.versions.length}
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
