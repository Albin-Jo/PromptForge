import * as React from "react";
import { ResponsiveContainer, Tooltip } from "recharts";

import { cn } from "@/lib/utils";

// shadcn's chart wrapper, trimmed to what we own and use (the upstream file targets Recharts 2
// internals; this is the same idea against Recharts 3). The core trick: a `ChartConfig` maps each
// data-series key to a label + a *theme* color (a `var(--chart-N)` token). `ChartContainer` emits
// those as scoped `--color-<key>` CSS variables, so a series that paints with `var(--color-<key>)`
// inherits our light/dark tokens automatically — no per-chart color wiring, no theme prop drilling.

export type ChartConfig = Record<
  string,
  {
    label?: React.ReactNode;
    // A CSS color — almost always a token, e.g. "var(--chart-1)" — so dark mode just works.
    color?: string;
  }
>;

// The row shape our chart primitives consume. A string index signature (not a constrained generic)
// is deliberate: Recharts 3's `dataKey` only accepts a plain `string` key when `string extends
// keyof Row`, which holds for this open record but not for an abstract `<Row>`. Pages shape their
// data into this via the tested transforms in lib/metrics/timeseries, so the looser key typing
// here is contained.
export type ChartDatum = Record<string, string | number | null | undefined>;

const ChartContext = React.createContext<{ config: ChartConfig } | null>(null);

export function useChart() {
  const ctx = React.useContext(ChartContext);
  if (!ctx) throw new Error("useChart must be used within a <ChartContainer>");
  return ctx;
}

// Inject `--color-<key>` variables scoped to this chart instance, so each series can reference its
// configured color via `stroke="var(--color-requests)"` etc. Returns null when nothing's coloured.
function ChartStyle({ id, config }: { id: string; config: ChartConfig }) {
  const colored = Object.entries(config).filter(([, v]) => v.color);
  if (!colored.length) return null;
  const css = `[data-chart="${id}"] {\n${colored
    .map(([key, v]) => `  --color-${key}: ${v.color};`)
    .join("\n")}\n}`;
  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}

export function ChartContainer({
  config,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig;
  children: React.ComponentProps<typeof ResponsiveContainer>["children"];
}) {
  const uid = React.useId();
  const id = `chart-${uid.replace(/:/g, "")}`;
  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-slot="chart"
        data-chart={id}
        className={cn(
          "flex aspect-video justify-center text-xs",
          // Theme Recharts' built-in SVG bits with our tokens instead of its hard-coded greys.
          "[&_.recharts-cartesian-grid_line]:stroke-border/60",
          "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground",
          "[&_.recharts-cartesian-axis-line]:stroke-border",
          "[&_.recharts-tooltip-cursor]:stroke-border",
          "[&_.recharts-curve.recharts-tooltip-cursor]:stroke-border",
          "[&_.recharts-radial-bar-background-sector]:fill-muted",
          className,
        )}
        {...props}
      >
        <ChartStyle id={id} config={config} />
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

// Recharts' own <Tooltip>; pair its `content` prop with <ChartTooltipContent>.
export const ChartTooltip = Tooltip;

// One entry as Recharts hands it to a tooltip `content` renderer (loosely typed — Recharts 3's
// payload type is internal and noisy; we read only the few fields we render).
interface TooltipItem {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string;
  color?: string;
}

export function ChartTooltipContent({
  active,
  payload,
  label,
  hideLabel = false,
  labelFormatter,
  valueFormatter,
}: {
  active?: boolean;
  payload?: TooltipItem[];
  label?: React.ReactNode;
  hideLabel?: boolean;
  labelFormatter?: (label: unknown) => React.ReactNode;
  // Format a series' value for display (e.g. ms, %, $); name is the series key.
  valueFormatter?: (value: number | string | undefined, name: string) => React.ReactNode;
}) {
  const { config } = useChart();
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-popover text-popover-foreground grid min-w-32 gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-md">
      {!hideLabel && (
        <div className="text-foreground font-medium">
          {labelFormatter ? labelFormatter(label) : label}
        </div>
      )}
      <div className="grid gap-1">
        {payload.map((item, i) => {
          const key = String(item.dataKey ?? item.name ?? i);
          const seriesLabel = config[key]?.label ?? item.name ?? key;
          return (
            <div key={key + i} className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <span
                  className="size-2 shrink-0 rounded-[2px]"
                  style={{ background: `var(--color-${key})` }}
                />
                {seriesLabel}
              </span>
              <span className="text-foreground font-medium tabular-nums">
                {valueFormatter ? valueFormatter(item.value, key) : item.value}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
