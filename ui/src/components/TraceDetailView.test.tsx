import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TraceDetailView } from "./TraceDetailView";
import { useTrace } from "../lib/traces/api";
import type { TraceDetail } from "../lib/traces/types";

vi.mock("../lib/traces/api", () => ({ useTrace: vi.fn() }));
const mockedUseTrace = vi.mocked(useTrace);

function setTrace(
  data: TraceDetail | undefined,
  state: Partial<ReturnType<typeof useTrace>> = {},
) {
  mockedUseTrace.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
    ...state,
  } as unknown as ReturnType<typeof useTrace>);
}

const detail: TraceDetail = {
  id: "t1",
  prompt_id: "p",
  prompt_version_id: "v1",
  source: "sdk",
  provider: "openai",
  model: "gpt-4o",
  provider_model: "gpt-4o-2026",
  request_id: "req-123",
  cost_usd: "0.000450",
  latency_ms: 1234,
  status: "ok",
  created_at: "2026-06-29T12:00:00Z",
  input: "RENDERED PROMPT",
  output: "MODEL OUTPUT",
  input_tokens: 10,
  output_tokens: 5,
  total_tokens: 15,
  error_type: null,
};

beforeEach(() => vi.clearAllMocks());

describe("TraceDetailView", () => {
  it("prompts the user to pick a trace when none is selected", () => {
    setTrace(undefined);
    render(<TraceDetailView traceId={undefined} />);
    expect(screen.getByText(/select a trace to inspect/i)).toBeInTheDocument();
    expect(useTrace).toHaveBeenCalledWith(undefined);
  });

  it("renders the rendered prompt, output and metadata with copy buttons", () => {
    setTrace(detail);
    render(<TraceDetailView traceId="t1" />);

    expect(screen.getByText("RENDERED PROMPT")).toBeInTheDocument();
    expect(screen.getByText("MODEL OUTPUT")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-2026")).toBeInTheDocument(); // served model
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(screen.getByText("1,234 ms")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy prompt" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy output" })).toBeInTheDocument();
  });

  it("shows the error type as the status when the call failed", () => {
    setTrace({ ...detail, status: "error", error_type: "RateLimitError", output: null });
    render(<TraceDetailView traceId="t1" />);
    expect(screen.getByText("RateLimitError")).toBeInTheDocument();
    expect(screen.getByText(/not captured for this execution/i)).toBeInTheDocument();
  });
});
