// The per-prompt traces page (Sprint 24, T3/T4): a paged, version-filterable list of executions
// with a drill-down into any one. A prompt-level tab (traces span versions), so it sits in
// PromptTabs alongside Editor / Versions / Dashboard.

import { useParams } from "react-router-dom";
import { PromptTabs } from "../components/PromptTabs";
import { QueryState } from "../components/QueryState";
import { TracesPanel } from "../components/TracesPanel";
import { usePrompt } from "../lib/prompts/api";

export function TracesPage() {
  const { name } = useParams();
  const query = usePrompt(name);

  return (
    <div>
      <h1 className="text-xl font-semibold">{name} — traces</h1>
      {name && (
        <div className="mt-4">
          <PromptTabs name={name} />
        </div>
      )}
      <QueryState query={query} label="prompt">
        {(prompt) => {
          // Newest-first version numbers feed the list's version filter.
          const versions = [...prompt.versions]
            .map((v) => v.version_number)
            .sort((a, b) => b - a);
          return (
            <div className="mt-2">
              <TracesPanel name={name} versions={versions} />
            </div>
          );
        }}
      </QueryState>
    </div>
  );
}
