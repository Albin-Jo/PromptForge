// Wire type for the render-cache hit-rate endpoint (Sprint 29 T4). Mirrors the API's
// CacheStatsResponse (api/src/promptforge_api/schemas.py).

/**
 * Cumulative render-cache outcomes for one prompt. `hit_rate` is null when there's been no render
 * traffic yet (total === 0); `ttl_seconds` is the cache TTL, for staleness context.
 */
export interface CacheStats {
  prompt: string;
  hits: number;
  misses: number;
  total: number;
  hit_rate: number | null;
  ttl_seconds: number;
}
