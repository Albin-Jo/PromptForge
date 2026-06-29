import { cn } from "@/lib/utils";
import type { MetricsWindow } from "@/lib/metrics/types";

const WINDOWS: MetricsWindow[] = ["24h", "7d", "30d"];

// A small segmented control for the observability window, shared by the overview home and the
// per-prompt dashboard so the two never drift in style or option set. Themed on the design tokens
// (the selected pill rides `--background` over a `--muted` track), so it follows light/dark.
export function MetricsWindowToggle({
  value,
  onChange,
}: {
  value: MetricsWindow;
  onChange: (window: MetricsWindow) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Time window"
      className="bg-muted inline-flex items-center rounded-lg p-0.5"
    >
      {WINDOWS.map((w) => (
        <button
          key={w}
          type="button"
          onClick={() => onChange(w)}
          aria-pressed={w === value}
          className={cn(
            "rounded-md px-2.5 py-1 text-sm font-medium transition-colors",
            w === value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {w}
        </button>
      ))}
    </div>
  );
}
