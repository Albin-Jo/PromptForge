import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
  type ChartDatum,
} from "@/components/ui/chart";

// One series to draw: which row field it reads, its legend label, and the theme token it paints
// with (a `var(--chart-N)`). Multiple series share one x-axis.
export interface TrendSeries {
  key: string;
  label: string;
  color: string;
}

interface TrendChartProps {
  data: ChartDatum[];
  // The field holding each row's x value (a time bucket — an ISO string or epoch ms).
  xKey: string;
  series: TrendSeries[];
  // "area" for a single filled trend (traffic/cost), "line" for comparisons. Default "line".
  variant?: "line" | "area";
  xTickFormatter?: (value: unknown) => string;
  yTickFormatter?: (value: number) => string;
  // Fix the y-axis to a known range (e.g. [0, 1] for a quality score) instead of auto-scaling to the
  // data. Omit to let recharts pick the domain from the values.
  yDomain?: [number, number];
  tooltipLabelFormatter?: (value: unknown) => string;
  tooltipValueFormatter?: (value: number | string | undefined, name: string) => string;
  className?: string;
  "aria-label"?: string;
}

/**
 * A themed line/area trend over a shared x-axis, built on the shadcn chart wrapper so every series
 * inherits its `var(--chart-N)` token in light and dark. Pages shape their rows into `ChartDatum`
 * (see lib/metrics/timeseries) and pass a `series` list.
 */
export function TrendChart({
  data,
  xKey,
  series,
  variant = "line",
  xTickFormatter,
  yTickFormatter,
  yDomain,
  tooltipLabelFormatter,
  tooltipValueFormatter,
  className,
  "aria-label": ariaLabel,
}: TrendChartProps) {
  const config: ChartConfig = Object.fromEntries(
    series.map((s) => [s.key, { label: s.label, color: s.color }]),
  );

  const Chart = variant === "area" ? AreaChart : LineChart;
  const resolvedAriaLabel = ariaLabel ?? series.map((s) => s.label).join(", ") + " trend";

  return (
    <ChartContainer config={config} className={className} role="img" aria-label={resolvedAriaLabel}>
      <Chart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey={xKey}
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
          tickFormatter={xTickFormatter}
        />
        <YAxis
          width={44}
          tickLine={false}
          axisLine={false}
          tickMargin={6}
          domain={yDomain}
          tickFormatter={yTickFormatter}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={tooltipLabelFormatter}
              valueFormatter={tooltipValueFormatter}
            />
          }
        />
        {series.map((s) =>
          variant === "area" ? (
            <Area
              key={s.key}
              dataKey={s.key}
              type="monotone"
              stroke={`var(--color-${s.key})`}
              fill={`var(--color-${s.key})`}
              fillOpacity={0.15}
              strokeWidth={2}
              // null buckets (gap-filled empties) break the line instead of dropping to 0.
              connectNulls={false}
              dot={false}
            />
          ) : (
            <Line
              key={s.key}
              dataKey={s.key}
              type="monotone"
              stroke={`var(--color-${s.key})`}
              strokeWidth={2}
              connectNulls={false}
              dot={false}
            />
          ),
        )}
      </Chart>
    </ChartContainer>
  );
}
