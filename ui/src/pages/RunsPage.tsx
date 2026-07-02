// The per-version run history (Sprint 24, T5): every eval run and every security scan for one
// version, newest first, each with drill-in. A version-scoped page reached from the dashboard
// action row and the versions table — the same way Scan and Playground are surfaced.

import { useParams } from "react-router-dom";
import { PromptTabs } from "../components/PromptTabs";
import { EvalRunsList } from "../components/EvalRunsList";
import { ScanRunsList } from "../components/ScanRunsList";

export function RunsPage() {
  const { name, versionNumber } = useParams();
  const version = versionNumber !== undefined ? Number(versionNumber) : undefined;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {name} — v{versionNumber} runs
      </h1>
      {name && (
        <div>
          <PromptTabs name={name} />
        </div>
      )}
      <EvalRunsList name={name} versionNumber={version} />
      <ScanRunsList name={name} versionNumber={version} />
    </div>
  );
}
