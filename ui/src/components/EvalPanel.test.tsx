import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { EvalPanel } from "./EvalPanel";
import { usePromptMetrics } from "../lib/metrics/api";
import { useVersionEval } from "../lib/evals/api";
import type { PromptMetrics } from "../lib/metrics/types";
import type { VersionEvalStatus } from "../lib/evals/types";

vi.mock("../lib/metrics/api", () => ({ usePromptMetrics: vi.fn() }));
// EvalPanel now also triggers + role-gates the on-demand run (Sprint 16e); stub those.
vi.mock("../lib/evals/api", () => ({
  useVersionEval: vi.fn(),
  useTriggerEval: () => ({ mutate: vi.fn(), isPending: false }),
  isEvalRunning: (s: string) => s === "pending" || s === "running",
}));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => true }));
const mockedUseMetrics = vi.mocked(usePromptMetrics);
const mockedUseEval = vi.mocked(useVersionEval);

function metricsWithVersions(versions: PromptMetrics["by_version"]): PromptMetrics {
  return {
    name: "p",
    prompt_id: "id",
    window: "7d",
    since: "2026-06-14T00:00:00Z",
    overall: {
      request_count: 0,
      error_count: 0,
      error_rate: null,
      latency: { p50_ms: null, p95_ms: null, p99_ms: null },
      total_cost_usd: null,
    },
    by_version: versions,
    by_source: [],
  };
}

function setMetrics(state: Partial<ReturnType<typeof usePromptMetrics>>) {
  mockedUseMetrics.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof usePromptMetrics>);
}

function setEval(data: VersionEvalStatus | undefined, state: Partial<ReturnType<typeof useVersionEval>> = {}) {
  mockedUseEval.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
    ...state,
  } as unknown as ReturnType<typeof useVersionEval>);
}

beforeEach(() => vi.clearAllMocks());

describe("EvalPanel data states", () => {
  it("shows the empty state when there are no versions", () => {
    setMetrics({ data: metricsWithVersions([]) });
    setEval(undefined);
    render(<EvalPanel name="p" window="7d" />);
    expect(screen.getByText(/no versions to evaluate yet/i)).toBeInTheDocument();
  });

  it("renders the scorer breakdown for the selected version on success", () => {
    setMetrics({
      data: metricsWithVersions([
        {
          version_number: 1,
          prompt_version_id: "v1",
          quality: 0.8,
          metrics: {
            request_count: 0,
            error_count: 0,
            error_rate: null,
            latency: { p50_ms: null, p95_ms: null, p99_ms: null },
            total_cost_usd: null,
          },
        },
      ]),
    });
    setEval({
      prompt: "p",
      version_number: 1,
      prompt_version_id: "v1",
      status: "completed",
      latest_run_id: "r1",
      summary: {
        items: 3,
        scored: 6,
        errors: 0,
        scorers: { llm_judge: { count: 3, passed: 3, pass_rate: 1, mean_value: 0.9 } },
      },
    });
    render(<EvalPanel name="p" window="7d" />);

    expect(screen.getByText("llm_judge")).toBeInTheDocument();
    expect(screen.getByText("3/3")).toBeInTheDocument(); // passed/count
    expect(screen.getByText(/3 items · 6 scored · 0 errors/i)).toBeInTheDocument();
  });

  it("transitions the run button from running to scored as the polled status updates", () => {
    setMetrics({
      data: metricsWithVersions([
        {
          version_number: 1,
          prompt_version_id: "v1",
          quality: null,
          metrics: {
            request_count: 0,
            error_count: 0,
            error_rate: null,
            latency: { p50_ms: null, p95_ms: null, p99_ms: null },
            total_cost_usd: null,
          },
        },
      ]),
    });

    // First poll: the run is still in flight.
    setEval({
      prompt: "p",
      version_number: 1,
      prompt_version_id: "v1",
      status: "running",
      latest_run_id: "r1",
      summary: null,
    });
    const { rerender } = render(<EvalPanel name="p" window="7d" />);
    expect(screen.getByRole("button", { name: /running…/i })).toBeDisabled();
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();

    // Next poll resolves to completed with scores — button frees up, breakdown renders.
    setEval({
      prompt: "p",
      version_number: 1,
      prompt_version_id: "v1",
      status: "completed",
      latest_run_id: "r1",
      summary: {
        items: 3,
        scored: 3,
        errors: 0,
        scorers: { llm_judge: { count: 3, passed: 3, pass_rate: 1, mean_value: 0.9 } },
      },
    });
    rerender(<EvalPanel name="p" window="7d" />);
    expect(screen.getByRole("button", { name: /run eval/i })).toBeEnabled();
    expect(screen.getByText("llm_judge")).toBeInTheDocument();
  });

  it("shows 'not evaluated yet' when the selected version has no run", () => {
    setMetrics({
      data: metricsWithVersions([
        {
          version_number: 1,
          prompt_version_id: "v1",
          quality: null,
          metrics: {
            request_count: 0,
            error_count: 0,
            error_rate: null,
            latency: { p50_ms: null, p95_ms: null, p99_ms: null },
            total_cost_usd: null,
          },
        },
      ]),
    });
    setEval({
      prompt: "p",
      version_number: 1,
      prompt_version_id: "v1",
      status: "unevaluated",
      latest_run_id: null,
      summary: null,
    });
    render(<EvalPanel name="p" window="7d" />);
    expect(screen.getByText(/not evaluated yet/i)).toBeInTheDocument();
  });
});
