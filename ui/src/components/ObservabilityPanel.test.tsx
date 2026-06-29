import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ObservabilityPanel } from "./ObservabilityPanel";
import { usePromptMetrics, usePromptTimeseries } from "../lib/metrics/api";
import type { PromptMetrics } from "../lib/metrics/types";

vi.mock("../lib/metrics/api", () => ({
  usePromptMetrics: vi.fn(),
  usePromptTimeseries: vi.fn(),
}));
// The By-version table resolves the live label pointers to mark the serving version. Stub them as
// unset so the table renders without a QueryClient.
vi.mock("../lib/prompts/api", () => ({
  useResolveLabel: vi.fn(() => ({ data: null })),
}));
const mockedUseMetrics = vi.mocked(usePromptMetrics);
const mockedUseTimeseries = vi.mocked(usePromptTimeseries);

function metrics(overrides: Partial<PromptMetrics> = {}): PromptMetrics {
  return {
    name: "p",
    prompt_id: "id",
    window: "7d",
    since: "2026-06-14T00:00:00Z",
    overall: {
      request_count: 10,
      error_count: 1,
      error_rate: 0.1,
      latency: { p50_ms: 120, p95_ms: 480, p99_ms: 900 },
      total_cost_usd: "0.050000",
    },
    by_version: [
      {
        version_number: 2,
        prompt_version_id: "v2",
        quality: 0.92,
        metrics: {
          request_count: 6,
          error_count: 0,
          error_rate: 0,
          latency: { p50_ms: 110, p95_ms: 460, p99_ms: 800 },
          total_cost_usd: "0.030000",
        },
      },
    ],
    by_source: [],
    ...overrides,
  };
}

function mockState(state: {
  isPending?: boolean;
  isError?: boolean;
  error?: Error | null;
  data?: PromptMetrics;
}) {
  mockedUseMetrics.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof usePromptMetrics>);
}

function renderPanel() {
  render(<ObservabilityPanel name="p" window="7d" />);
}

beforeEach(() => {
  vi.clearAllMocks();
  // The trend + per-version sparklines fetch their own time-series; default them to pending so the
  // success test exercises the metrics-driven tables without needing a bucket fixture.
  mockedUseTimeseries.mockReturnValue({
    isPending: true,
    isError: false,
    error: null,
    data: undefined,
  } as unknown as ReturnType<typeof usePromptTimeseries>);
});

describe("ObservabilityPanel data states", () => {
  it("shows a loading skeleton while pending", () => {
    mockState({ isPending: true });
    renderPanel();
    expect(
      screen.getByRole("status", { name: /loading metrics…/i }),
    ).toBeInTheDocument();
  });

  it("shows an error line on failure", () => {
    mockState({ isError: true, error: new Error("nope") });
    renderPanel();
    expect(screen.getByText(/could not load metrics: nope/i)).toBeInTheDocument();
  });

  it("shows the empty state when there are no executions in the window", () => {
    mockState({ data: metrics({ overall: { ...metrics().overall, request_count: 0 } }) });
    renderPanel();
    expect(screen.getByText(/no executions recorded in this window/i)).toBeInTheDocument();
  });

  it("renders stats and per-version rows on success", () => {
    mockState({ data: metrics() });
    renderPanel();
    expect(screen.getByText("By version")).toBeInTheDocument(); // section rendered
    expect(screen.getByText("10")).toBeInTheDocument(); // overall request count
    expect(screen.getByText("v2")).toBeInTheDocument(); // version row
    expect(screen.getByText("$0.05")).toBeInTheDocument(); // formatted overall cost
  });
});
