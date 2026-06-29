import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { VersionComparison } from "./VersionComparison";
import { usePromptMetrics, usePromptTimeseries } from "../lib/metrics/api";
import type { PromptMetrics, VersionMetrics } from "../lib/metrics/types";

vi.mock("../lib/metrics/api", () => ({
  usePromptMetrics: vi.fn(),
  usePromptTimeseries: vi.fn(),
}));
const mockedUseMetrics = vi.mocked(usePromptMetrics);
const mockedUseTimeseries = vi.mocked(usePromptTimeseries);

function version(n: number, overrides: Partial<VersionMetrics> = {}): VersionMetrics {
  return {
    version_number: n,
    prompt_version_id: `v${n}`,
    quality: 0.8,
    metrics: {
      request_count: n * 10,
      error_count: 0,
      error_rate: 0,
      latency: { p50_ms: 100, p95_ms: 200, p99_ms: 300 },
      total_cost_usd: "0.010000",
    },
    ...overrides,
  };
}

function metrics(by_version: VersionMetrics[]): PromptMetrics {
  return {
    name: "p",
    prompt_id: "id",
    window: "7d",
    since: "2026-06-14T00:00:00Z",
    overall: {
      request_count: 30,
      error_count: 0,
      error_rate: 0,
      latency: { p50_ms: 100, p95_ms: 200, p99_ms: 300 },
      total_cost_usd: "0.030000",
    },
    by_version,
    by_source: [],
  };
}

function setMetrics(data: PromptMetrics | undefined) {
  mockedUseMetrics.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data,
  } as unknown as ReturnType<typeof usePromptMetrics>);
}

function renderView() {
  render(<VersionComparison name="p" window="7d" />);
}

beforeEach(() => {
  vi.clearAllMocks();
  // The per-version trend is a separate query; pending keeps the test focused on the metrics table.
  mockedUseTimeseries.mockReturnValue({
    isPending: true,
    isError: false,
    error: null,
    data: undefined,
  } as unknown as ReturnType<typeof usePromptTimeseries>);
});

describe("VersionComparison", () => {
  it("prompts for a second version when only one exists", () => {
    setMetrics(metrics([version(1)]));
    renderView();
    expect(screen.getByText(/Add a second version to compare/)).toBeInTheDocument();
  });

  it("renders two version selectors and a side-by-side metric table", () => {
    setMetrics(metrics([version(1), version(2), version(3)]));
    renderView();
    // Two selectors, defaulting to the two latest versions.
    expect(screen.getByLabelText("Version A")).toBeInTheDocument();
    expect(screen.getByLabelText("Version B")).toBeInTheDocument();
    // The comparison table lists the headline metrics.
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("Error rate")).toBeInTheDocument();
    expect(screen.getByText("p95 latency (ms)")).toBeInTheDocument();
    expect(screen.getByText("Quality (0–1)")).toBeInTheDocument();
    // Default columns are v2 and v3 (the two latest) — shown as column headers.
    expect(screen.getByRole("columnheader", { name: "v2" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "v3" })).toBeInTheDocument();
  });
});
