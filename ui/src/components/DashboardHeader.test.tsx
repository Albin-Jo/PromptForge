import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardHeader } from "./DashboardHeader";
import { usePrompt, useResolveLabel } from "../lib/prompts/api";
import { usePromptMetrics } from "../lib/metrics/api";
import { useCan } from "../lib/auth/AuthContext";
import type { Prompt, PromptVersion } from "../lib/prompts/types";

vi.mock("../lib/prompts/api", () => ({ usePrompt: vi.fn(), useResolveLabel: vi.fn() }));
vi.mock("../lib/metrics/api", () => ({ usePromptMetrics: vi.fn() }));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: vi.fn(() => false) }));
// Stub the promote dialog so this test exercises only the header's own logic (latest-version
// computation + promote gating), not the dialog's mutation/gate machinery.
vi.mock("./PromoteDialog", () => ({
  PromoteDialog: ({ versionNumber, canPromote }: { versionNumber: number; canPromote: boolean }) => (
    <div data-testid="promote">
      v{versionNumber}:{String(canPromote)}
    </div>
  ),
}));

const mockedUsePrompt = vi.mocked(usePrompt);
const mockedUseResolveLabel = vi.mocked(useResolveLabel);
const mockedUseMetrics = vi.mocked(usePromptMetrics);
const mockedUseCan = vi.mocked(useCan);

function version(n: number): PromptVersion {
  return {
    id: `v${n}`,
    version_number: n,
    parent_version_id: null,
    content: "",
    input_variables: [],
    model_settings: null,
    output_schema: null,
    created_at: "",
    blocks: [],
  };
}

function setVersions(nums: number[]) {
  mockedUsePrompt.mockReturnValue({
    data: { versions: nums.map(version) } as Prompt,
  } as unknown as ReturnType<typeof usePrompt>);
}

// Resolve "production"/"staging" → a version number, or null when unset.
function setLabels(map: Record<string, number | null>) {
  mockedUseResolveLabel.mockImplementation(
    (_name: string | undefined, label: string) =>
      ({
        data: map[label] != null ? { version_number: map[label] } : null,
      }) as unknown as ReturnType<typeof useResolveLabel>,
  );
}

function renderHeader() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DashboardHeader name="p" window="7d" onWindowChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedUseCan.mockReturnValue(false);
  mockedUseMetrics.mockReturnValue({
    dataUpdatedAt: 0,
    isFetching: false,
  } as unknown as ReturnType<typeof usePromptMetrics>);
  setLabels({});
});

describe("DashboardHeader", () => {
  it("renders a live badge for each resolved label, naming the version it points at", () => {
    setVersions([1, 2, 3]);
    setLabels({ production: 3, staging: null });
    renderHeader();
    expect(screen.getByText(/production · v3/)).toBeInTheDocument();
    // Staging is unset → no staging badge.
    expect(screen.queryByText(/staging/)).not.toBeInTheDocument();
  });

  it("targets Promote at the latest version", () => {
    setVersions([1, 2, 5, 3]);
    renderHeader();
    expect(screen.getByTestId("promote")).toHaveTextContent("v5:false");
  });

  it("passes admin capability through to Promote", () => {
    mockedUseCan.mockReturnValue(true);
    setVersions([1]);
    renderHeader();
    expect(screen.getByTestId("promote")).toHaveTextContent("v1:true");
  });

  it("omits Promote when the prompt has no versions", () => {
    setVersions([]);
    renderHeader();
    expect(screen.queryByTestId("promote")).not.toBeInTheDocument();
  });
});
