import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvalRunsList, overallPassRate } from "./EvalRunsList";
import { useVersionEvals } from "../lib/evals/api";
import type { EvalRunSummary } from "../lib/evals/types";

vi.mock("../lib/evals/api", () => ({ useVersionEvals: vi.fn() }));
const mockedUseRuns = vi.mocked(useVersionEvals);

function setRuns(
  data: EvalRunSummary[] | undefined,
  state: Partial<ReturnType<typeof useVersionEvals>> = {},
) {
  mockedUseRuns.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
    ...state,
  } as unknown as ReturnType<typeof useVersionEvals>);
}

const completedRun: EvalRunSummary = {
  id: "r2",
  status: "completed",
  scorers: ["llm_judge"],
  created_at: "2026-06-29T12:00:00Z",
  completed_at: "2026-06-29T12:01:00Z",
  summary: {
    items: 3,
    scored: 3,
    errors: 0,
    scorers: { llm_judge: { count: 3, passed: 3, pass_rate: 1, mean_value: 0.9 } },
  },
};

const pendingRun: EvalRunSummary = {
  id: "r1",
  status: "pending",
  scorers: ["llm_judge"],
  created_at: "2026-06-29T11:00:00Z",
  completed_at: null,
  summary: null,
};

beforeEach(() => vi.clearAllMocks());

describe("overallPassRate", () => {
  it("sums passed/count across scorers", () => {
    expect(
      overallPassRate({
        items: 2,
        scored: 4,
        errors: 0,
        scorers: {
          a: { count: 2, passed: 1, pass_rate: 0.5, mean_value: 0.5 },
          b: { count: 2, passed: 2, pass_rate: 1, mean_value: 1 },
        },
      }),
    ).toBe(0.75);
  });

  it("is null when nothing was scored or summary is absent", () => {
    expect(overallPassRate(null)).toBeNull();
    expect(overallPassRate({ items: 0, scored: 0, errors: 0, scorers: {} })).toBeNull();
  });
});

describe("EvalRunsList", () => {
  it("shows the empty state when there are no runs", () => {
    setRuns([]);
    render(<EvalRunsList name="p" versionNumber={1} />);
    expect(screen.getByText(/no evals have run for this version/i)).toBeInTheDocument();
  });

  it("lists runs with scorers and outcome, newest first as given", () => {
    setRuns([completedRun, pendingRun]);
    render(<EvalRunsList name="p" versionNumber={1} />);

    const rows = screen.getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Evaluated")).toBeInTheDocument();
    expect(within(rows[1]).getByText("In progress")).toBeInTheDocument();
    // The completed run shows its 100% aggregate pass rate.
    expect(within(rows[0]).getByText("100.0%")).toBeInTheDocument();
  });

  it("drills into a run's scorer breakdown on click", async () => {
    const user = userEvent.setup();
    setRuns([completedRun]);
    render(<EvalRunsList name="p" versionNumber={1} />);

    // The breakdown is hidden until the row is expanded.
    expect(screen.queryByText(/3 items · 3 scored · 0 errors/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button"));
    expect(screen.getByText(/3 items · 3 scored · 0 errors/i)).toBeInTheDocument();
    // "llm_judge" now appears twice: the row's Scorers column and the expanded breakdown table.
    expect(screen.getAllByText("llm_judge")).toHaveLength(2);
  });
});
