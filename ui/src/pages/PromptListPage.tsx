import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText } from "lucide-react";
import { usePrompts } from "../lib/prompts/api";
import type { PromptSummary } from "../lib/prompts/types";
import { QueryState } from "../components/QueryState";
import { EmptyState } from "../components/EmptyState";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";

function matches(prompt: PromptSummary, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return (
    prompt.name.toLowerCase().includes(q) ||
    (prompt.description ?? "").toLowerCase().includes(q)
  );
}

export function PromptListPage() {
  const query = usePrompts();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Prompts</h1>
        <Button asChild>
          <Link to="/prompts/new">New prompt</Link>
        </Button>
      </div>

      <Input
        type="search"
        placeholder="Search prompts…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mt-4 max-w-md"
      />

      <div className="mt-6">
        <QueryState
          query={query}
          label="prompts"
          isEmpty={(prompts) => prompts.length === 0}
          empty={
            <EmptyState
              icon={FileText}
              title="No prompts yet"
              description="Create your first prompt to start versioning and testing it."
              action={{
                label: "New prompt",
                onClick: () => navigate("/prompts/new"),
              }}
            />
          }
        >
          {(prompts) => {
            // Client-side filter (ADR 0019 / Task 4 decision: fine at v0.1 scale).
            const filtered = prompts.filter((p) => matches(p, search));
            if (filtered.length === 0) {
              return (
                <EmptyState
                  icon={FileText}
                  title={`No prompts match “${search}”`}
                  description="Try a different search term."
                />
              );
            }
            return (
              <Card className="py-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead className="text-right">Latest</TableHead>
                      <TableHead className="text-right">Versions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((p) => (
                      <TableRow key={p.name}>
                        <TableCell>
                          <Link
                            to={`/prompts/${encodeURIComponent(p.name)}/edit`}
                            className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          >
                            {p.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {p.description ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-right">
                          {p.latest_version ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-right">
                          {p.version_count}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            );
          }}
        </QueryState>
      </div>
    </div>
  );
}
