import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useBlock, useBlockImpact } from "../lib/blocks/api";
import { useCan } from "../lib/auth/AuthContext";
import { QueryState } from "../components/QueryState";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import type { Block } from "../lib/blocks/types";

// Above this many deps, collapse the list and show a toggle.
const IMPACT_COLLAPSE_AT = 12;

type DepRow = { label: string; version: number; href: string };

function DepList({ rows, label }: { rows: DepRow[]; label: string }) {
  const [expanded, setExpanded] = useState(false);
  const overflow = rows.length - IMPACT_COLLAPSE_AT;
  const visible = expanded || overflow <= 0 ? rows : rows.slice(0, IMPACT_COLLAPSE_AT);

  return (
    <div>
      <p className="mb-1.5 text-xs font-medium text-foreground">
        {label} <span className="text-muted-foreground">({rows.length})</span>
      </p>
      <ul className="space-y-1" aria-label={label}>
        {visible.map((r) => (
          <li key={`${r.label}-${r.version}`} className="flex items-center justify-between gap-3 rounded-md border px-3 py-1.5">
            <Link
              to={r.href}
              className="min-w-0 truncate text-sm font-medium hover:underline"
            >
              {r.label}
            </Link>
            <Badge variant="outline" className="shrink-0 font-mono text-xs">
              v{r.version}
            </Badge>
          </li>
        ))}
      </ul>
      {overflow > 0 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          {expanded ? "Show less" : `Show ${overflow} more`}
        </button>
      )}
    </div>
  );
}

function ImpactCard({ name }: { name: string }) {
  const { data, isPending, isError } = useBlockImpact(name, true);

  const promptRows: DepRow[] = (data?.prompts ?? []).map((p) => ({
    label: p.name,
    version: p.version_number,
    href: `/prompts/${encodeURIComponent(p.name)}/versions`,
  }));
  const blockRows: DepRow[] = (data?.blocks ?? []).map((b) => ({
    label: b.name,
    version: b.version_number,
    href: `/blocks/${encodeURIComponent(b.name)}`,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Impact</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        {isPending && "Loading impact…"}
        {isError && <span className="text-destructive">Could not load impact.</span>}
        {data && (
          <>
            <p className="mb-4">
              Used by {data.prompts.length} prompt version{data.prompts.length === 1 ? "" : "s"} and{" "}
              {data.blocks.length} block version{data.blocks.length === 1 ? "" : "s"}.
            </p>
            {promptRows.length > 0 && <DepList rows={promptRows} label="Prompt versions" />}
            {blockRows.length > 0 && (
              <div className={promptRows.length > 0 ? "mt-4" : ""}>
                <DepList rows={blockRows} label="Block versions" />
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function BlockBody({ block }: { block: Block }) {
  const canEdit = useCan("editor");
  // Version history newest-first.
  const versions = [...block.versions].sort((a, b) => b.version_number - a.version_number);

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{block.name}</h1>
          <Badge variant="secondary">{block.role}</Badge>
        </div>
        {canEdit && (
          <Button asChild>
            <Link to={`/blocks/${encodeURIComponent(block.name)}/versions/new`}>New version</Link>
          </Button>
        )}
      </div>
      {block.description && (
        <p className="mt-1 text-sm text-muted-foreground">{block.description}</p>
      )}

      <div className="mt-6">
        <ImpactCard name={block.name} />
      </div>

      <h2 className="mt-8 text-sm font-medium text-foreground">Version history</h2>
      <div className="mt-3 space-y-3">
        {versions.map((v) => (
          <Card key={v.id}>
            <CardHeader>
              <CardTitle className="text-sm">
                v{v.version_number}
                {v.input_variables.length > 0 && (
                  <span className="ml-2 font-normal text-muted-foreground">
                    variables: {v.input_variables.join(", ")}
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md bg-muted/50 p-3 font-mono text-xs text-foreground whitespace-pre-wrap">
                {v.content}
              </pre>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function BlockDetailPage() {
  const { name } = useParams();
  const query = useBlock(name);

  return (
    <QueryState query={query} label="block">
      {(block) => <BlockBody block={block} />}
    </QueryState>
  );
}
