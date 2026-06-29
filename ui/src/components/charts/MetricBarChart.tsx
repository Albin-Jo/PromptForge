import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
  type ChartDatum,
} from "@/components/ui/chart";

interface MetricBarChartProps {
  data: ChartDatum[];
  // The categorical field on the x-axis (e.g. "v1", "v2", or a source name).
  xKey: string;
  // The single numeric field to bar; labelled and coloured via a `var(--chart-N)` token.
  valueKey: string;
  label: string;
  color: string;
  layout?: "horizontal" | "vertical";
  xTickFormatter?: (value: unknown) => string;
  yTickFormatter?: (value: number) => string;
  tooltipValueFormatter?: (value: number | string | undefined, name: string) => string;
  className?: string;
}

/**
 * A themed single-series bar chart for categorical comparisons (per-version requests, cost-by-source).
 * `layout="vertical"` puts categories down the y-axis — handy when there are many or long labels.
 */
export function MetricBarChart({
  data,
  xKey,
  valueKey,
  label,
  color,
  layout = "horizontal",
  xTickFormatter,
  yTickFormatter,
  tooltipValueFormatter,
  className,
}: MetricBarChartProps) {
  const config: ChartConfig = { [valueKey]: { label, color } };
  const vertical = layout === "vertical";

  return (
    <ChartContainer config={config} className={className}>
      <BarChart
        data={data}
        layout={layout}
        margin={{ left: 4, right: 8, top: 8, bottom: 0 }}
      >
        <CartesianGrid horizontal={!vertical} vertical={vertical} />
        {vertical ? (
          <>
            <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={yTickFormatter} />
            <YAxis
              type="category"
              dataKey={xKey}
              tickLine={false}
              axisLine={false}
              width={80}
              tickFormatter={xTickFormatter}
            />
          </>
        ) : (
          <>
            <XAxis
              dataKey={xKey}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={xTickFormatter}
            />
            <YAxis width={44} tickLine={false} axisLine={false} tickFormatter={yTickFormatter} />
          </>
        )}
        <ChartTooltip content={<ChartTooltipContent valueFormatter={tooltipValueFormatter} />} />
        <Bar dataKey={valueKey} fill={`var(--color-${valueKey})`} radius={4} />
      </BarChart>
    </ChartContainer>
  );
}
