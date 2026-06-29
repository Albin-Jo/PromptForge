import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

// One place for the loading / error / empty / success branching every data page repeats.
// Extracted so the data-state behaviour is tested once (Sprint 16 DoD) and every dashboard
// renders these states identically. The success branch uses a render prop so TypeScript narrows
// `data` to non-null — callers don't re-guard it.

// The slice of a React Query result this component needs. Structural so any useQuery result fits.
interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error?: { message?: string } | null;
  data?: T;
  /** React Query's refetch. Optional so any query-shaped object fits; when present, the error
   *  state offers a Retry button. Every real useQuery result carries it, so Retry is universal. */
  refetch?: () => void;
}

interface QueryStateProps<T> {
  query: QueryLike<T>;
  /** Success render; `data` is guaranteed defined here. */
  children: (data: T) => ReactNode;
  /** Noun used in the default loading/error messages, e.g. "metrics" -> "Loading metrics…". */
  label?: string;
  /** Optional emptiness check; when it returns true, the empty slot renders instead of children. */
  isEmpty?: (data: T) => boolean;
  /** What to show when isEmpty(data) is true. Ignored if isEmpty is not provided. */
  empty?: ReactNode;
  /** Override the default skeleton with a shape-matched one (e.g. table rows). */
  loading?: ReactNode;
}

// Default loading slot: a few shimmering Skeleton lines instead of a "Loading…" string
// (Sprint 16d DoD). Wrapped in role="status" + aria-label so screen readers still get
// a spoken "Loading metrics…" and tests have a queryable handle now there's no text.
function DefaultSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={`Loading ${label}…`} className="space-y-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
    </div>
  );
}

export function QueryState<T>({
  query,
  children,
  label = "data",
  isEmpty,
  empty,
  loading,
}: QueryStateProps<T>): ReactNode {
  // Error first: a failed fetch outranks a stale/absent body.
  if (query.isError) {
    const message = query.error?.message ?? "unknown error";
    return (
      <div className="space-y-2">
        <p className="text-sm text-destructive">Could not load {label}: {message}</p>
        {query.refetch && (
          <Button size="sm" variant="outline" onClick={() => query.refetch?.()}>
            Retry
          </Button>
        )}
      </div>
    );
  }

  if (query.isPending || query.data === undefined) {
    return loading ?? <DefaultSkeleton label={label} />;
  }

  if (isEmpty?.(query.data)) {
    return <>{empty}</>;
  }

  return <>{children(query.data)}</>;
}
