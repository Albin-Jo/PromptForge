import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { History, Play, ShieldCheck } from "lucide-react";
import { usePrompt, useResolveLabel } from "../lib/prompts/api";
import type { Prompt, PromptVersion } from "../lib/prompts/types";
import { useCan } from "../lib/auth/AuthContext";
import { DiffView } from "../components/DiffView";
import { PromoteDialog } from "../components/PromoteDialog";
import { PromptTabs } from "../components/PromptTabs";
import { QueryState } from "../components/QueryState";
import { Badge } from "../components/ui/badge";
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
import { cn } from "../lib/utils";

// Native <select> restyled onto tokens — same pattern as the other dense inline pickers.
const selectClasses =
  "rounded-md border border-input bg-background text-foreground shadow-sm px-2 py-1 text-sm " +
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function VersionHistoryPage() {
  const { name } = useParams();
  const query = usePrompt(name);

  return (
    <div>
      <h1 className="text-xl font-semibold">{name} — version history</h1>
      {name && (
        <div className="mt-4">
          <PromptTabs name={name} />
        </div>
      )}
      <QueryState query={query} label="versions">
        {(prompt) => <VersionHistoryBody name={name ?? ""} prompt={prompt} />}
      </QueryState>
    </div>
  );
}

function VersionHistoryBody({ name, prompt }: { name: string; prompt: Prompt }) {
  // Versions come oldest-first from the API; newest-first reads better as history.
  const versions: PromptVersion[] = [...prompt.versions].sort(
    (a, b) => b.version_number - a.version_number,
  );

  // Promote is admin-only; the dialog itself disables+tooltips for non-admins.
  const canPromote = useCan("admin");

  // Resolve the live label pointers so each row can badge production/staging (404 = unset).
  // These re-fetch automatically when a promote succeeds (the mutation invalidates label keys).
  const production = useResolveLabel(name, "production");
  const staging = useResolveLabel(name, "staging");
  function labelsFor(versionNumber: number): ("production" | "staging")[] {
    const out: ("production" | "staging")[] = [];
    if (production.data?.version_number === versionNumber) out.push("production");
    if (staging.data?.version_number === versionNumber) out.push("staging");
    return out;
  }

  // Default the diff to the two most recent versions (newest as "to").
  const [fromNumber, setFromNumber] = useState<number | null>(null);
  const [toNumber, setToNumber] = useState<number | null>(null);

  const newest = versions[0];
  const previous = versions[1];
  const from = versions.find((v) => v.version_number === (fromNumber ?? previous?.version_number));
  const to = versions.find((v) => v.version_number === (toNumber ?? newest?.version_number));

  return (
    <>
      {versions.length === 0 && (
        <p className="mt-6 text-sm text-muted-foreground">No versions yet.</p>
      )}

      {versions.length > 0 && (
        <>
          <Card className="mt-6 py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Labels</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Variables</TableHead>
                  <TableHead>Blocks</TableHead>
                  <TableHead className="text-right">Scan</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                  <TableHead className="text-right">Run</TableHead>
                  <TableHead className="text-right">Promote</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium text-foreground">v{v.version_number}</TableCell>
                    <TableCell>
                      <span className="flex flex-wrap gap-1">
                        {labelsFor(v.version_number).map((l) => (
                          <Badge key={l} variant={l === "production" ? "success" : "secondary"}>
                            {l}
                          </Badge>
                        ))}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(v.created_at)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {v.input_variables.length > 0 ? v.input_variables.join(", ") : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{v.blocks.length || "—"}</TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="outline">
                        <Link
                          to={`/prompts/${encodeURIComponent(name)}/versions/${v.version_number}/scan`}
                        >
                          <ShieldCheck /> Scan
                        </Link>
                      </Button>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="outline">
                        <Link
                          to={`/prompts/${encodeURIComponent(name)}/versions/${v.version_number}/runs`}
                        >
                          <History /> Runs
                        </Link>
                      </Button>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="outline">
                        <Link
                          to={`/prompts/${encodeURIComponent(name)}/versions/${v.version_number}/playground`}
                        >
                          <Play /> Playground
                        </Link>
                      </Button>
                    </TableCell>
                    <TableCell className="text-right">
                      <PromoteDialog
                        name={name}
                        versionNumber={v.version_number}
                        canPromote={canPromote}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          {versions.length < 2 ? (
            <p className="mt-6 text-sm text-muted-foreground">
              Only one version so far — nothing to diff yet.
            </p>
          ) : (
            <div className="mt-8">
              <div className="flex items-center gap-3 text-sm">
                <label className="flex items-center gap-2">
                  <span className="text-muted-foreground">From</span>
                  <select
                    aria-label="Diff from version"
                    value={from?.version_number ?? ""}
                    onChange={(e) => setFromNumber(Number(e.target.value))}
                    className={cn(selectClasses)}
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.version_number}>
                        v{v.version_number}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-2">
                  <span className="text-muted-foreground">To</span>
                  <select
                    aria-label="Diff to version"
                    value={to?.version_number ?? ""}
                    onChange={(e) => setToNumber(Number(e.target.value))}
                    className={cn(selectClasses)}
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.version_number}>
                        v{v.version_number}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {from && to && (
                <div className="mt-4">
                  <DiffView
                    oldText={from.content}
                    newText={to.content}
                    oldLabel={`v${from.version_number}`}
                    newLabel={`v${to.version_number}`}
                  />
                </div>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
