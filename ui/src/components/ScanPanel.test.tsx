import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ScanPanel } from "./ScanPanel";
import { usePrompt } from "../lib/prompts/api";
import { useVersionScan } from "../lib/scans/api";
import type { Finding, VersionScanStatus } from "../lib/scans/types";
import type { Prompt } from "../lib/prompts/types";

vi.mock("../lib/prompts/api", () => ({ usePrompt: vi.fn() }));
vi.mock("../lib/scans/api", () => ({
  useVersionScan: vi.fn(),
  useTriggerScan: () => ({ mutate: vi.fn(), isPending: false }),
  isScanRunning: (s: string) => s === "pending" || s === "running",
}));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => true }));

const mockedUsePrompt = vi.mocked(usePrompt);
const mockedUseScan = vi.mocked(useVersionScan);

function promptWithVersions(nums: number[]): Prompt {
  return {
    id: "id",
    name: "p",
    description: null,
    created_at: "",
    updated_at: "",
    golden_set_id: null,
    versions: nums.map((n) => ({
      id: `v${n}`,
      version_number: n,
      parent_version_id: null,
      content: "",
      input_variables: [],
      model_settings: null,
      output_schema: null,
      created_at: "",
      blocks: [],
    })),
  };
}

function scan(overrides: Partial<VersionScanStatus> = {}): VersionScanStatus {
  return {
    prompt: "p",
    version_number: 2,
    prompt_version_id: "v2",
    status: "completed",
    latest_scan_id: "s1",
    risk_level: "none",
    findings: [],
    ...overrides,
  };
}

function finding(): Finding {
  return {
    category: "injection",
    severity: "high",
    detector: "regex",
    message: "looks injectable",
    evidence: "ignore previous…",
    span: null,
    metadata: {},
  };
}

function setPrompt(data: Prompt | undefined) {
  mockedUsePrompt.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
  } as unknown as ReturnType<typeof usePrompt>);
}

function setScan(data: VersionScanStatus | undefined) {
  mockedUseScan.mockReturnValue({
    isPending: data === undefined,
    isError: false,
    error: null,
    data,
  } as unknown as ReturnType<typeof useVersionScan>);
}

function renderPanel() {
  render(
    <MemoryRouter>
      <ScanPanel name="p" />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("ScanPanel", () => {
  it("shows the empty state when the prompt has no versions", () => {
    setPrompt(promptWithVersions([]));
    setScan(undefined);
    renderPanel();
    expect(screen.getByText(/no versions to scan yet/i)).toBeInTheDocument();
  });

  it("summarises a clean completed scan with no findings", () => {
    setPrompt(promptWithVersions([1, 2]));
    setScan(scan({ status: "completed", risk_level: "none", findings: [] }));
    renderPanel();
    expect(screen.getByText("Risk level")).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getByText(/0 findings/)).toBeInTheDocument();
    // Nothing to investigate → no findings link.
    expect(screen.queryByRole("link", { name: /view findings/i })).not.toBeInTheDocument();
  });

  it("shows the risk level, finding count, and a findings link for a flagged scan", () => {
    setPrompt(promptWithVersions([1, 2]));
    setScan(scan({ status: "completed", risk_level: "high", findings: [finding()] }));
    renderPanel();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/1 finding\b/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view findings/i })).toHaveAttribute(
      "href",
      "/prompts/p/versions/2/scan",
    );
  });

  it("prompts the user to scan an unscanned version, with the run action available", () => {
    setPrompt(promptWithVersions([1, 2]));
    setScan(scan({ status: "unscanned", risk_level: null, findings: null }));
    renderPanel();
    expect(screen.getByText(/not scanned yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run scan/i })).toBeEnabled();
  });
});
