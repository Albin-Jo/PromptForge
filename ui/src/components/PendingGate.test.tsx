import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PendingGate } from "./PromoteDialog";
import { useVersionEval } from "../lib/evals/api";
import { useVersionScan } from "../lib/scans/api";
import type { VersionEvalStatus } from "../lib/evals/types";
import type { VersionScanStatus } from "../lib/scans/types";

// Drive the gate's polled status by hand so we can assert the running → ready transition without
// real timers. Keep the running predicates real so the component's terminal check is exercised.
vi.mock("../lib/evals/api", () => ({
  useVersionEval: vi.fn(),
  isEvalRunning: (s: string) => s === "pending" || s === "running",
}));
vi.mock("../lib/scans/api", () => ({
  useVersionScan: vi.fn(),
  isScanRunning: (s: string) => s === "pending" || s === "running",
}));

const mockedEval = vi.mocked(useVersionEval);
const mockedScan = vi.mocked(useVersionScan);

function evalData(status: VersionEvalStatus["status"] | undefined) {
  mockedEval.mockReturnValue({
    data: status === undefined ? undefined : ({ status } as VersionEvalStatus),
  } as unknown as ReturnType<typeof useVersionEval>);
}
function scanData(status: VersionScanStatus["status"] | undefined) {
  mockedScan.mockReturnValue({
    data: status === undefined ? undefined : ({ status } as VersionScanStatus),
  } as unknown as ReturnType<typeof useVersionScan>);
}

beforeEach(() => {
  vi.clearAllMocks();
  // Default both to "no data" so only the gate under test drives state.
  evalData(undefined);
  scanData(undefined);
});

describe("PendingGate (eval gate)", () => {
  it("keeps Retry disabled while the eval runs, then enables it when the eval completes", () => {
    const onRetry = vi.fn();
    evalData("running");
    const pending = { detail: "evaluation in progress", eval_run_id: "r1" };

    const { rerender } = render(
      <PendingGate name="p" versionNumber={3} pending={pending} onRetry={onRetry} retrying={false} />,
    );
    expect(screen.getByText(/waiting for the evaluation to finish/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry promote/i })).toBeDisabled();

    // Next poll: the eval finished — the gate is ready and Retry frees up.
    evalData("completed");
    rerender(
      <PendingGate name="p" versionNumber={3} pending={pending} onRetry={onRetry} retrying={false} />,
    );
    const retry = screen.getByRole("button", { name: /retry promote/i });
    expect(retry).toBeEnabled();
    expect(screen.getByText(/gate finished/i)).toBeInTheDocument();

    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("PendingGate (scan gate)", () => {
  it("watches the scan instead when the pending body carries a security_scan_id", () => {
    const onRetry = vi.fn();
    scanData("running");
    const pending = { detail: "security scan in progress", security_scan_id: "s1" };

    const { rerender } = render(
      <PendingGate name="p" versionNumber={3} pending={pending} onRetry={onRetry} retrying={false} />,
    );
    expect(screen.getByText(/waiting for the security scan to finish/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry promote/i })).toBeDisabled();

    scanData("completed");
    rerender(
      <PendingGate name="p" versionNumber={3} pending={pending} onRetry={onRetry} retrying={false} />,
    );
    expect(screen.getByRole("button", { name: /retry promote/i })).toBeEnabled();
  });
});
