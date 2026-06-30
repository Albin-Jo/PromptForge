import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScanRunsList } from "./ScanRunsList";
import { useVersionScans } from "../lib/scans/api";
import type { Finding, ScanRunSummary } from "../lib/scans/types";

vi.mock("../lib/scans/api", () => ({ useVersionScans: vi.fn() }));
const mockedUseScans = vi.mocked(useVersionScans);

function setScans(
  data: ScanRunSummary[] | undefined,
  state: Partial<ReturnType<typeof useVersionScans>> = {},
) {
  mockedUseScans.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
    ...state,
  } as unknown as ReturnType<typeof useVersionScans>);
}

const injectionFinding: Finding = {
  category: "injection",
  severity: "high",
  detector: "instruction-override",
  message: "Possible prompt injection",
  evidence: "ignore previous…",
  span: null,
  metadata: {},
};

const completedScan: ScanRunSummary = {
  id: "s2",
  status: "completed",
  scanners: ["injection", "pii"],
  risk_level: "high",
  findings: [injectionFinding],
  created_at: "2026-06-29T12:00:00Z",
  completed_at: "2026-06-29T12:00:30Z",
};

const pendingScan: ScanRunSummary = {
  id: "s1",
  status: "pending",
  scanners: [],
  risk_level: null,
  findings: null,
  created_at: "2026-06-29T11:00:00Z",
  completed_at: null,
};

beforeEach(() => vi.clearAllMocks());

describe("ScanRunsList", () => {
  it("shows the empty state when there are no scans", () => {
    setScans([]);
    render(<ScanRunsList name="p" versionNumber={1} />);
    expect(screen.getByText(/no scans have run for this version/i)).toBeInTheDocument();
  });

  it("lists scans with risk + finding count, in-progress for a pending scan", () => {
    setScans([completedScan, pendingScan]);
    render(<ScanRunsList name="p" versionNumber={1} />);

    const rows = screen.getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("high")).toBeInTheDocument();
    expect(within(rows[0]).getByText("1")).toBeInTheDocument(); // finding count
    expect(within(rows[1]).getByText("In progress")).toBeInTheDocument();
    expect(within(rows[1]).getByText("—")).toBeInTheDocument(); // count unknown while pending
  });

  it("drills into a scan's findings on click", async () => {
    const user = userEvent.setup();
    setScans([completedScan]);
    render(<ScanRunsList name="p" versionNumber={1} />);

    expect(screen.queryByText("Possible prompt injection")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button"));
    // The grouped findings render: the injection category header + the finding's message + detector.
    expect(screen.getByText("Possible prompt injection")).toBeInTheDocument();
    expect(screen.getByText("instruction-override")).toBeInTheDocument();
  });
});
