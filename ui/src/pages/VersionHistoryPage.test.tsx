import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { VersionHistoryPage } from "./VersionHistoryPage";
import { usePrompt } from "../lib/prompts/api";
import type { PromptVersion } from "../lib/prompts/types";

// The page now also resolves labels + offers Promote (Sprint 16e). Stub those so this suite stays
// focused on version-history rendering; the promote flow is covered by PromoteDialog's own tests.
vi.mock("../lib/prompts/api", () => ({
  usePrompt: vi.fn(),
  useResolveLabel: () => ({ data: undefined }),
  useSetLabel: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false }),
}));
// Default to non-admin so Promote renders its disabled+tooltip branch (no QueryClient needed).
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => false }));
const mockedUsePrompt = vi.mocked(usePrompt);

function version(n: number, content: string): PromptVersion {
  return {
    id: `v${n}`,
    version_number: n,
    parent_version_id: n > 1 ? `v${n - 1}` : null,
    content,
    input_variables: [],
    model_settings: null,
    output_schema: null,
    created_at: `2026-01-0${n}T00:00:00Z`,
    blocks: [],
  };
}

function mockVersions(versions: PromptVersion[]) {
  mockedUsePrompt.mockReturnValue({
    data: { id: "p", name: "p", description: null, created_at: "", updated_at: "", versions },
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof usePrompt>);
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/prompts/p/versions"]}>
      <Routes>
        <Route path="/prompts/:name/versions" element={<VersionHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("VersionHistoryPage", () => {
  it("lists versions newest-first with a playground link each", () => {
    // API order is oldest-first; the page should reverse it.
    mockVersions([version(1, "a"), version(2, "a")]);
    renderPage();

    const links = screen.getAllByRole("link", { name: /playground/i });
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/versions/2/playground"));
  });

  it("defaults the diff to the two most recent versions", () => {
    mockVersions([version(1, "a\nb"), version(2, "a\nc")]);
    renderPage();

    // v1 -> v2 changed "b" to "c": expect one added and one removed row.
    expect(document.querySelector('[data-diff-type="added"]')).not.toBeNull();
    expect(document.querySelector('[data-diff-type="removed"]')).not.toBeNull();
  });

  it("shows nothing-to-diff when there is only one version", () => {
    mockVersions([version(1, "only")]);
    renderPage();

    expect(screen.getByText(/nothing to diff/i)).toBeInTheDocument();
    expect(document.querySelector("[data-diff-type]")).toBeNull();
  });
});
