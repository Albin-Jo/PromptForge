import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "./ui/button";
import { formatRelative } from "../lib/metrics/format";
import { cn } from "../lib/utils";

// Surfaces how fresh a background-refetching query is, with a manual refresh. The aggregate metrics
// re-fetch on an interval (METRICS_REFETCH_MS); this tells the user when they last did and lets them
// force one. `isFetching` reflects any in-flight fetch (background or manual).
export function FreshnessIndicator({
  updatedAt,
  isFetching,
  onRefresh,
}: {
  updatedAt: number;
  isFetching: boolean;
  onRefresh: () => void;
}) {
  // Re-tick once a second so "Ns ago" advances while the panel sits open.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="text-muted-foreground flex items-center gap-1 text-xs">
      <span className="tabular-nums">
        {isFetching
          ? "updating…"
          : `updated ${updatedAt ? formatRelative(updatedAt, now, "compact") : "—"}`}
      </span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        aria-label="Refresh metrics"
        onClick={onRefresh}
        disabled={isFetching}
      >
        <RefreshCw className={cn("size-3", isFetching && "animate-spin")} />
      </Button>
    </div>
  );
}
