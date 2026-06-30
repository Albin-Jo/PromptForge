import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TracesList } from "./TracesList";
import { useTraces } from "../lib/traces/api";
import type { TraceSummary } from "../lib/traces/types";

vi.mock("../lib/traces/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/traces/api")>("../lib/traces/api");
  return { ...actual, useTraces: vi.fn() };
});
const mockedUseTraces = vi.mocked(useTraces);

function setTraces(
  data: TraceSummary[] | undefined,
  state: Partial<ReturnType<typeof useTraces>> = {},
) {
  mockedUseTraces.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
    ...state,
  } as unknown as ReturnType<typeof useTraces>);
}

function trace(id: string, over: Partial<TraceSummary> = {}): TraceSummary {
  return {
    id,
    prompt_id: "p",
    prompt_version_id: "v1",
    source: "sdk",
    provider: "openai",
    model: "gpt-4o",
    cost_usd: "0.000450",
    latency_ms: 1234,
    status: "ok",
    created_at: "2026-06-29T12:00:00Z",
    ...over,
  };
}

const noop = () => {};

beforeEach(() => vi.clearAllMocks());

describe("TracesList", () => {
  it("shows the empty state when there are no traces", () => {
    setTraces([]);
    render(<TracesList name="p" versions={[1]} selectedId={undefined} onSelect={noop} />);
    expect(screen.getByText(/no executions recorded/i)).toBeInTheDocument();
  });

  it("renders a row per trace with model, latency and cost", () => {
    setTraces([trace("t1"), trace("t2", { status: "error", latency_ms: 50, cost_usd: null })]);
    render(<TracesList name="p" versions={[1]} selectedId={undefined} onSelect={noop} />);

    expect(screen.getAllByRole("button", { expanded: false })).toHaveLength(2);
    expect(screen.getByText("1,234 ms")).toBeInTheDocument();
    expect(screen.getByText("$0.00045")).toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("calls onSelect with the trace id when a row is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    setTraces([trace("t1")]);
    render(<TracesList name="p" versions={[1]} selectedId={undefined} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { expanded: false }));
    expect(onSelect).toHaveBeenCalledWith("t1");
  });

  it("disables Previous on the first page and Next on a short page", () => {
    setTraces([trace("t1")]); // one row < page size → no next page
    render(<TracesList name="p" versions={[1]} selectedId={undefined} onSelect={noop} />);

    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });
});
