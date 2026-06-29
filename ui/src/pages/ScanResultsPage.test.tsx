import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ScanResultsPage } from "./ScanResultsPage";
import { useVersionScan } from "../lib/scans/api";
import type { Finding, VersionScanStatus } from "../lib/scans/types";

// ScanResultsPage now also triggers + role-gates the on-demand scan (Sprint 16e); stub those.
vi.mock("../lib/scans/api", () => ({
  useVersionScan: vi.fn(),
  useTriggerScan: () => ({ mutate: vi.fn(), isPending: false }),
  isScanRunning: (s: string) => s === "pending" || s === "running",
}));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => true }));
const mockedUseScan = vi.mocked(useVersionScan);

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    category: "secret",
    severity: "high",
    detector: "aws_access_key_id",
    message: "Possible AWS access key id",
    evidence: "AKIA…last4",
    span: null,
    metadata: {},
    ...overrides,
  };
}

function setScan(state: Partial<ReturnType<typeof useVersionScan>>) {
  mockedUseScan.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useVersionScan>);
}

function scan(overrides: Partial<VersionScanStatus> = {}): VersionScanStatus {
  return {
    prompt: "p",
    version_number: 1,
    prompt_version_id: "v1",
    status: "completed",
    latest_scan_id: "s1",
    risk_level: "none",
    findings: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/prompts/p/versions/1/scan"]}>
      <Routes>
        <Route path="/prompts/:name/versions/:versionNumber/scan" element={<ScanResultsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("ScanResultsPage data states", () => {
  it("shows a loading skeleton while pending", () => {
    setScan({ isPending: true });
    renderPage();
    expect(
      screen.getByRole("status", { name: /loading scan results…/i }),
    ).toBeInTheDocument();
  });

  it("shows an error line on failure", () => {
    setScan({ isError: true, error: new Error("boom") });
    renderPage();
    expect(screen.getByText(/could not load scan results: boom/i)).toBeInTheDocument();
  });

  it("shows a clean message when completed with no findings", () => {
    setScan({ data: scan({ findings: [], risk_level: "none" }) });
    renderPage();
    expect(screen.getByText(/clean — no security findings/i)).toBeInTheDocument();
  });

  it("shows 'not scanned yet' for an unscanned version", () => {
    setScan({ data: scan({ status: "unscanned", findings: null, risk_level: null }) });
    renderPage();
    expect(screen.getByText(/hasn't been scanned yet/i)).toBeInTheDocument();
  });

  it("transitions the run button from scanning to done as the polled status updates", () => {
    // First poll: the scan is in flight.
    setScan({ data: scan({ status: "running", findings: null, risk_level: null }) });
    const { rerender } = renderPage();
    expect(screen.getByRole("button", { name: /scanning…/i })).toBeDisabled();
    expect(screen.getByText(/scan in progress/i)).toBeInTheDocument();

    // Next poll resolves clean — button frees up, result renders.
    setScan({ data: scan({ status: "completed", findings: [], risk_level: "none" }) });
    rerender(
      <MemoryRouter initialEntries={["/prompts/p/versions/1/scan"]}>
        <Routes>
          <Route path="/prompts/:name/versions/:versionNumber/scan" element={<ScanResultsPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: /run scan/i })).toBeEnabled();
    expect(screen.getByText(/clean — no security findings/i)).toBeInTheDocument();
  });

  it("renders findings grouped with the risk level when present", () => {
    setScan({
      data: scan({
        risk_level: "high",
        findings: [finding(), finding({ category: "pii", severity: "medium", detector: "email", message: "Email address" })],
      }),
    });
    renderPage();

    expect(screen.getByText("Secrets")).toBeInTheDocument();
    expect(screen.getByText("PII")).toBeInTheDocument();
    expect(screen.getByText("Possible AWS access key id")).toBeInTheDocument();
    expect(screen.getByText(/2 findings/i)).toBeInTheDocument();
  });
});
