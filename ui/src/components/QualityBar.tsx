import { formatQuality } from "../lib/metrics/format";

function qualityFill(v: number): string {
  if (v < 0.5) return "bg-destructive";
  if (v < 0.8) return "bg-warning";
  return "bg-success";
}

// A thin 0–1 quality bar with its formatted value, shared by the eval and observability
// surfaces (16d dedup — these were two drifting copies). App component, not a ui/ primitive,
// because it knows about our quality formatting.
export function QualityBar({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="bg-muted h-1.5 w-24 overflow-hidden rounded-full">
        <div
          className={`${qualityFill(value)} h-full`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="text-muted-foreground tabular-nums">{formatQuality(value)}</span>
    </div>
  );
}
