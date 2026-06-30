import { Database } from "lucide-react";

import { useCacheStats } from "../lib/cache/api";
import { Card, CardContent } from "./ui/card";

// Admin-only render-cache health (Sprint 29 T4): the SDK render-by-label hit-rate for this prompt.
// Fetched only when `isAdmin`, so a non-admin viewing the dashboard never calls the admin-gated
// endpoint. Supplementary, so it degrades quietly — while loading or on error it renders nothing
// rather than disturbing the dashboard. The rate is cumulative + per-process (see the API's
// CacheStats), so it's an at-a-glance signal, not an accounting figure.
export function CacheTile({ name, isAdmin }: { name: string; isAdmin: boolean }) {
  const query = useCacheStats(name, isAdmin);

  if (!isAdmin || !query.data) return null;
  const stats = query.data;
  const noTraffic = stats.hit_rate === null;

  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-4 py-4">
        <div className="flex items-center gap-2">
          <Database className="text-muted-foreground size-4 shrink-0" />
          <div>
            <p className="text-sm font-medium">Render cache</p>
            <p className="text-muted-foreground text-xs">
              {noTraffic
                ? "No render traffic yet"
                : `${stats.hits}/${stats.total} served from cache · TTL ${stats.ttl_seconds}s`}
            </p>
          </div>
        </div>
        <p className="text-2xl font-semibold tabular-nums">
          {noTraffic ? "—" : `${Math.round((stats.hit_rate ?? 0) * 100)}%`}
        </p>
      </CardContent>
    </Card>
  );
}
