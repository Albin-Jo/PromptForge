// Shared rendering for a scan's findings, grouped by category and worst-first within each group.
// Extracted from ScanResultsPage so the per-version scan page and the scan run-history drill-in
// (ScanRunsList) render findings identically rather than forking the markup (Sprint 24, T2).

import type { Category, Finding, Severity } from "../lib/scans/types";
import { SeverityBadge } from "./SeverityBadge";
import { Card, CardContent } from "./ui/card";

const SEVERITY_RANK: Record<Severity, number> = { low: 0, medium: 1, high: 2 };

const CATEGORY_LABEL: Record<Category, string> = {
  injection: "Prompt injection",
  pii: "PII",
  secret: "Secrets",
  jailbreak: "Jailbreak",
};

// Stable display order for the category groups.
const CATEGORY_ORDER: Category[] = ["injection", "jailbreak", "secret", "pii"];

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <li className="border-b border-border py-3 last:border-b-0">
      <div className="flex items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <code className="text-xs text-muted-foreground">{finding.detector}</code>
      </div>
      <p className="mt-1 text-sm text-foreground">{finding.message}</p>
      {finding.evidence && (
        <div className="mt-1">
          <span className="text-xs text-muted-foreground">evidence (redacted): </span>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">
            {finding.evidence}
          </code>
        </div>
      )}
    </li>
  );
}

export function FindingsByCategory({ findings }: { findings: Finding[] }) {
  // Bucket by category, then sort each bucket worst-first.
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: findings
      .filter((f) => f.category === category)
      .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]),
  })).filter((g) => g.items.length > 0);

  return (
    <Card className="mt-6">
      <CardContent className="space-y-6">
        {groups.map((group) => (
          <section key={group.category}>
            <h3 className="mb-1 text-sm font-medium text-foreground">
              {CATEGORY_LABEL[group.category]}{" "}
              <span className="font-normal text-muted-foreground">({group.items.length})</span>
            </h3>
            <ul>
              {group.items.map((f, i) => (
                <FindingCard key={`${f.detector}-${i}`} finding={f} />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
