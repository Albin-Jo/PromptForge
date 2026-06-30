// Wire types for the operational-health endpoint (Sprint 29 T3). Mirrors the API's
// QueueHealthResponse / QueueDepthDTO (api/src/promptforge_api/schemas.py).

/** Pending (not-yet-delivered) message count for one Celery broker queue. */
export interface QueueDepth {
  name: string;
  depth: number;
}

/**
 * Celery queue/worker health. `available` is false when the broker can't be reached — every count
 * is null then (the endpoint degrades, never 500s). `workers`/`active` are null when the broker was
 * up but worker inspection failed; `queued` is the total backlog across `queues`.
 */
export interface QueueHealth {
  available: boolean;
  workers: number | null;
  active: number | null;
  queued: number | null;
  queues: QueueDepth[] | null;
}
