import { Line, LineChart, ResponsiveContainer } from "recharts";

interface SparklineProps {
  // The series to draw; nulls (empty buckets) leave gaps rather than dropping to 0.
  data: (number | null)[];
  // A CSS color — default the foreground muted token so it reads in light + dark.
  color?: string;
  // Fixed pixel width for inline/table-cell use. Omit to fill the parent (responsive) — e.g. in a
  // fluid stat card, where a fixed width would clip or leave dead space.
  width?: number;
  height?: number;
  className?: string;
  "aria-label"?: string;
}

/**
 * A compact, axis-less trend line — no grid, axes, or tooltip; a glance, not a chart. Pass a fixed
 * `width` for dense inline spots (e.g. a per-version trend in a table cell), or omit it to fill a
 * fluid container via a ResponsiveContainer. Height is always fixed so the row never reflows.
 */
export function Sparkline({
  data,
  color = "var(--muted-foreground)",
  width,
  height = 28,
  className,
  "aria-label": ariaLabel,
}: SparklineProps) {
  // Recharts wants a row per point; index is the implicit x.
  const rows = data.map((value, i) => ({ i, value }));
  const margin = { top: 2, bottom: 2, left: 0, right: 0 } as const;
  const line = (
    <Line
      dataKey="value"
      type="monotone"
      stroke={color}
      strokeWidth={1.5}
      dot={false}
      connectNulls={false}
      isAnimationActive={false}
    />
  );

  return (
    <div
      className={className}
      style={{ width: width ?? "100%", height }}
      role="img"
      aria-label={ariaLabel ?? "trend sparkline"}
    >
      {width !== undefined ? (
        <LineChart width={width} height={height} data={rows} margin={margin}>
          {line}
        </LineChart>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={rows} margin={margin}>
            {line}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
