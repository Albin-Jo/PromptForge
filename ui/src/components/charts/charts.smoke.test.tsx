import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricBarChart } from "./MetricBarChart";
import { Sparkline } from "./Sparkline";
import { TrendChart } from "./TrendChart";
import type { ChartDatum } from "@/components/ui/chart";

// Smoke-level proof the chart pipeline mounts (Recharts 3 + the shadcn wrapper + our tokens) and
// tolerates the gap-filled shape — null buckets and an all-empty series. jsdom has no layout, so
// ResponsiveContainer renders at 0×0 and won't draw SVG paths; we assert the wrapper mounts and the
// theming hook (`data-slot="chart"` / scoped `--color-*` style) is present, not pixel output.

const series: ChartDatum[] = [
  { bucket: "2026-06-22T00:00:00Z", requests: 10, p95: 200 },
  { bucket: "2026-06-23T00:00:00Z", requests: null, p95: null }, // gap-filled empty bucket
  { bucket: "2026-06-24T00:00:00Z", requests: 4, p95: 150 },
];

describe("chart primitives", () => {
  it("TrendChart mounts and injects scoped series colors", () => {
    const { container } = render(
      <TrendChart
        data={series}
        xKey="bucket"
        series={[{ key: "requests", label: "Requests", color: "var(--chart-1)" }]}
      />,
    );
    const chart = container.querySelector('[data-slot="chart"]');
    expect(chart).not.toBeNull();
    // The ChartStyle <style> wires --color-requests to the theme token, so dark mode follows.
    expect(container.querySelector("style")?.textContent).toContain("--color-requests");
  });

  it("TrendChart area variant tolerates an all-null series without throwing", () => {
    const empty: ChartDatum[] = series.map((r) => ({ ...r, requests: null }));
    expect(() =>
      render(
        <TrendChart
          data={empty}
          xKey="bucket"
          variant="area"
          series={[{ key: "requests", label: "Requests", color: "var(--chart-1)" }]}
        />,
      ),
    ).not.toThrow();
  });

  it("MetricBarChart mounts for categorical data", () => {
    const bars: ChartDatum[] = [
      { version: "v1", requests: 12 },
      { version: "v2", requests: 3 },
    ];
    const { container } = render(
      <MetricBarChart
        data={bars}
        xKey="version"
        valueKey="requests"
        label="Requests"
        color="var(--chart-2)"
      />,
    );
    expect(container.querySelector('[data-slot="chart"]')).not.toBeNull();
  });

  it("Sparkline renders a labelled, fixed-size glyph", () => {
    const { getByRole } = render(
      <Sparkline data={[1, null, 3, 2]} aria-label="v1 request trend" />,
    );
    expect(getByRole("img", { name: "v1 request trend" })).toBeInTheDocument();
  });
});
