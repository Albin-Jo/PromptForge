import { Link, useParams } from "react-router-dom";
import { useBlock, useBlockImpact } from "../lib/blocks/api";
import { useCan } from "../lib/auth/AuthContext";
import { QueryState } from "../components/QueryState";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import type { Block } from "../lib/blocks/types";

function ImpactCard({ name }: { name: string }) {
  const { data, isPending, isError } = useBlockImpact(name, true);
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
            <p>
              Used by {data.prompts.length} prompt version{data.prompts.length === 1 ? "" : "s"} and{" "}
              {data.blocks.length} block version{data.blocks.length === 1 ? "" : "s"}.
            </p>
            {data.prompts.length > 0 && (
              <p className="mt-2">
                Prompts:{" "}
                {data.prompts.map((p, i) => (
                  <span key={`${p.name}-${p.version_number}`}>
                    {i > 0 && ", "}
                    {p.name} v{p.version_number}
                  </span>
                ))}
              </p>
            )}
            {data.blocks.length > 0 && (
              <p className="mt-1">
                Blocks:{" "}
                {data.blocks.map((b, i) => (
                  <span key={`${b.name}-${b.version_number}`}>
                    {i > 0 && ", "}
                    {b.name} v{b.version_number}
                  </span>
                ))}
              </p>
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
