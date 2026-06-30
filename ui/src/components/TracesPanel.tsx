// The trace surface for one prompt (Sprint 24, T3+T4): a paged, version-filterable list of
// executions alongside the drill-down for the selected one. Master-detail — the list stays lean,
// the detail loads the full rendered prompt + output on demand.

import { useState } from "react";
import { TracesList } from "./TracesList";
import { TraceDetailView } from "./TraceDetailView";

export function TracesPanel({
  name,
  versions,
}: {
  name: string | undefined;
  versions: number[];
}) {
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <TracesList
        name={name}
        versions={versions}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
      <div className="lg:sticky lg:top-4 lg:self-start">
        <TraceDetailView traceId={selectedId} />
      </div>
    </div>
  );
}
