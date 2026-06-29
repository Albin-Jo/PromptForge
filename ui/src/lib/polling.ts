// One shared "poll until terminal" helper for async run/scan status (Sprint 16e).
//
// Async work (eval runs, security scans, the promote gate) starts in a non-terminal state and the
// UI must watch it to completion without a manual refresh. Rather than per-panel setInterval loops
// (easy to leak), we drive polling through React Query's `refetchInterval`: this builds a callback
// that re-fetches while the latest data is still "running" and returns `false` to STOP at a
// terminal state. React Query also pauses polling on a backgrounded tab by default
// (refetchIntervalInBackground is off), so this can't spin in the background.

export const POLL_INTERVAL_MS = 2000;

/**
 * Build a `refetchInterval` callback that polls every `intervalMs` while `isPending(data)` is true
 * and stops otherwise. Stops (returns false) before the first response and on a fetch error, so a
 * failing status endpoint never spins forever.
 *
 * The param is typed structurally (a slice of React Query's `Query`) to stay decoupled from its
 * generics while remaining assignable to the `refetchInterval` option.
 */
export function pollWhilePending<T>(
  isPending: (data: T) => boolean,
  intervalMs: number = POLL_INTERVAL_MS,
) {
  return (query: { state: { data: T | undefined; status: string } }): number | false => {
    if (query.state.data === undefined || query.state.status === "error") return false;
    return isPending(query.state.data) ? intervalMs : false;
  };
}
