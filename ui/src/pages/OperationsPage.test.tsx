import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationsPage } from "./OperationsPage";
import { useQueueHealth } from "../lib/ops/api";
import type { QueueHealth } from "../lib/ops/types";

vi.mock("../lib/ops/api", () => ({ useQueueHealth: vi.fn() }));
const mockedUseQueueHealth = vi.mocked(useQueueHealth);

function setHealth(state: Partial<ReturnType<typeof useQueueHealth>>) {
  mockedUseQueueHealth.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useQueueHealth>);
}

const HEALTHY: QueueHealth = {
  available: true,
  workers: 2,
  active: 1,
  queued: 3,
  queues: [
    { name: "celery", depth: 0 },
    { name: "evals", depth: 2 },
    { name: "scans", depth: 1 },
    { name: "traces", depth: 0 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("OperationsPage", () => {
  it("renders the headline counts and the per-queue backlog from a healthy snapshot", () => {
    setHealth({ data: HEALTHY });
    render(<OperationsPage />);

    expect(screen.getByText("Workers online")).toBeInTheDocument();
    expect(screen.getByText("Active tasks")).toBeInTheDocument();
    expect(screen.getByText("Queued (backlog)")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // total backlog (unique among the counts)

    // Each routed queue appears in the breakdown.
    for (const name of ["celery", "evals", "scans", "traces"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("shows an unavailable state, with no counts, when the broker is unreachable", () => {
    setHealth({
      data: { available: false, workers: null, active: null, queued: null, queues: null },
    });
    render(<OperationsPage />);

    expect(screen.getByText(/Broker unreachable/)).toBeInTheDocument();
    expect(screen.queryByText("Workers online")).not.toBeInTheDocument();
  });

  it("links out to Flower", () => {
    setHealth({ data: HEALTHY });
    render(<OperationsPage />);

    const link = screen.getByRole("link", { name: /Flower/i });
    expect(link).toHaveAttribute("href", "http://localhost:5555");
  });
});
