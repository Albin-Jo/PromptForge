// Display formatters for the observability dashboard. Kept pure + framework-free so they're
// trivially unit-testable and reusable across the metric tables.

const DASH = "—";

/** A latency in ms as "1,240 ms"; null (no data) renders as an em dash. */
export function formatMs(ms: number | null): string {
  if (ms === null) return DASH;
  return `${Math.round(ms).toLocaleString()} ms`;
}

/** A rate in [0,1] as a percentage ("2.1%"); null renders as an em dash. */
export function formatPct(rate: number | null): string {
  if (rate === null) return DASH;
  return `${(rate * 100).toFixed(1)}%`;
}

/** A quality score in [0,1] as a 2-decimal value ("0.92"); null renders as an em dash. */
export function formatQuality(value: number | null): string {
  if (value === null) return DASH;
  return value.toFixed(2);
}

/**
 * A coarse relative time for a freshness/cutoff hint. `value` is an ISO string or an epoch-ms number
 * (react-query's dataUpdatedAt). `style` picks the wording: "long" reads as "5 minutes ago" (the
 * since-cutoff line), "compact" as "5m ago" (the freshness chip). `now` is injectable so the output
 * is deterministic in tests. Invalid input falls back to the raw string / em dash, never "Invalid
 * Date".
 */
export function formatRelative(
  value: string | number,
  now: number = Date.now(),
  style: "long" | "compact" = "long",
): string {
  const then = typeof value === "number" ? value : new Date(value).getTime();
  if (Number.isNaN(then)) return typeof value === "string" ? value : DASH;
  const compact = style === "compact";
  const sec = Math.round((now - then) / 1000);
  if (sec < (compact ? 5 : 45)) return "just now";
  if (compact && sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return compact ? `${min}m ago` : `${min} minute${min === 1 ? "" : "s"} ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return compact ? `${hr}h ago` : `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.round(hr / 24);
  return compact ? `${day}d ago` : `${day} day${day === 1 ? "" : "s"} ago`;
}

/**
 * A money string (e.g. "0.000450") as a dollar display. The input is an exact decimal string from
 * the API — we never parseFloat it for arithmetic. For display we do read it as a Number purely to
 * choose precision: tiny sub-cent costs keep enough digits to not collapse to "$0.00", while normal
 * amounts show 2 decimals. null/absent renders as an em dash.
 */
export function formatCost(value: string | null): string {
  if (value === null) return DASH;
  const n = Number(value);
  if (Number.isNaN(n)) return DASH;
  if (n === 0) return "$0.00";
  // Below a cent, show enough significant digits to be meaningful (e.g. "$0.000450").
  if (n < 0.01) return `$${value.replace(/0+$/, "").replace(/\.$/, "")}`;
  // Round at the cent. The +ε offsets binary-float truncation — e.g. 0.015 is stored as
  // 0.01499…, so a plain n.toFixed(2) reads a cent low ("$0.01"); ε is far below any real cost.
  return `$${(Math.round(n * 100 + 1e-6) / 100).toFixed(2)}`;
}
