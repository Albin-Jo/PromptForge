import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OverviewPage } from "./OverviewPage";
import { useOverview } from "@/lib/overview/api";
import { usePrompts } from "@/lib/prompts/api";
import type { FleetOverview, PromptRollup } from "@/lib/overview/types";
import type { MetricsBucket } from "@/lib/metrics/types";

vi.mock("@/lib/overview/api", () => ({ useOverview: vi.fn() }));
vi.mock("@/lib/prompts/api", () => ({ usePrompts: vi.fn() }));

const mockedUseOverview = vi.mocked(useOverview);
const mockedUsePrompts = vi.mocked(usePrompts);

function bucket(start: string, requests: number): MetricsBucket {
  return {
    bucket_start: start,
    request_count: requests,
    error_rate: requests ? 0.1 : null,
    p50_ms: requests ? 100 : null,
    p95_ms: requests ? 200 : null,
    p99_ms: requests ? 350 : null,
    cost_usd: requests ? "0.002000" : null,
    quality: null,
  };
}

function rollup(overrides: Partial<PromptRollup> = {}): PromptRollup {
  return {
    name: "greet",
    latest_version: 2,
    request_count: 10,
    error_rate: 0.01,
    p95_ms: 180,
    cost_usd: "0.010000",
    quality: 0.9,
    attention: [],
    ...overrides,
  };
}

function overview(overrides: Partial<FleetOverview> = {}): FleetOverview {
  return {
    window: "7d",
    interval: "day",
    since: "2026-06-17T00:00:00Z",
    totals: {
      request_count: 15,
      error_count: 2,
      error_rate: 2 / 15,
      latency: { p50_ms: 120, p95_ms: 300, p99_ms: 400 },
      total_cost_usd: "0.015000",
    },
    trend: [bucket("2026-06-22T00:00:00Z", 0), bucket("2026-06-23T00:00:00Z", 15)],
    prompts: [rollup()],
    ...overrides,
  };
}

function setOverview(state: {
  isPending?: boolean;
  isError?: boolean;
  error?: { message?: string } | null;
  data?: FleetOverview;
}) {
  mockedUseOverview.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useOverview>);
  // The recent-activity strip reads the prompt list; default to empty unless a test overrides.
  mockedUsePrompts.mockReturnValue({ data: [] } as unknown as ReturnType<typeof usePrompts>);
}

function renderPage() {
  // OverviewPage uses useQueryClient (the refresh control) even though its data hooks are mocked.
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OverviewPage", () => {
  it("shows a loading state while pending", () => {
    setOverview({ isPending: true });
    renderPage();
    // The header always renders; the body is skeletons (no fleet numbers yet).
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.queryByText("Requests")).not.toBeInTheDocument();
  });

  it("surfaces an error", () => {
    setOverview({ isError: true, error: { message: "boom" } });
    renderPage();
    expect(screen.getByText(/Could not load overview: boom/)).toBeInTheDocument();
  });

  it("shows the empty state when no prompts exist", () => {
    setOverview({ data: overview({ prompts: [] }) });
    renderPage();
    expect(screen.getByText("No prompts yet")).toBeInTheDocument();
  });

  it("renders fleet totals and a healthy needs-attention state", () => {
    setOverview({ data: overview() });
    renderPage();
    // "Requests" now labels both the stat card and the all-prompts column — assert at least one.
    expect(screen.getAllByText("Requests").length).toBeGreaterThan(0);
    expect(screen.getByText("15")).toBeInTheDocument(); // total requests
    // No prompt is flagged → the healthy message, not a flagged row.
    expect(screen.getByText(/Every prompt looks healthy/)).toBeInTheDocument();
  });

  it("lists prompts needing attention with a badge per fired rule", () => {
    setOverview({
      data: overview({
        prompts: [
          rollup({ name: "noisy", attention: ["high_error_rate"], error_rate: 0.2 }),
          rollup({ name: "calm", attention: [] }),
        ],
      }),
    });
    renderPage();
    // Scope to the needs-attention list — both prompts also appear in the full all-prompts table.
    const attention = within(screen.getByRole("list", { name: "Needs attention" }));
    expect(attention.getByRole("link", { name: "noisy" })).toBeInTheDocument();
    expect(attention.getByText("High errors")).toBeInTheDocument();
    // The healthy prompt isn't listed in the attention section.
    expect(attention.queryByRole("link", { name: "calm" })).not.toBeInTheDocument();
  });

  it("lists every prompt in the sortable all-prompts table", () => {
    setOverview({
      data: overview({
        prompts: [
          rollup({ name: "noisy", attention: ["high_error_rate"], error_rate: 0.2 }),
          rollup({ name: "calm", attention: [] }),
        ],
      }),
    });
    renderPage();
    const all = within(screen.getByRole("table", { name: "All prompts" }));
    expect(all.getByRole("link", { name: "noisy" })).toBeInTheDocument();
    expect(all.getByRole("link", { name: "calm" })).toBeInTheDocument();
  });
});
