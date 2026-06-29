import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { PromptListPage } from "./PromptListPage";
import { usePrompts } from "@/lib/prompts/api";
import type { PromptSummary } from "@/lib/prompts/types";

vi.mock("@/lib/prompts/api", () => ({ usePrompts: vi.fn() }));

const mockedUsePrompts = vi.mocked(usePrompts);

function prompt(overrides: Partial<PromptSummary> = {}): PromptSummary {
  return {
    name: "greet",
    description: "Greets the user",
    latest_version: 3,
    version_count: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

function setPrompts(state: Partial<ReturnType<typeof usePrompts>>) {
  mockedUsePrompts.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as ReturnType<typeof usePrompts>);
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PromptListPage />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("PromptListPage", () => {
  it("renders a row per prompt", () => {
    setPrompts({ data: [prompt({ name: "greet" }), prompt({ name: "summarize" })] });
    renderPage();
    expect(screen.getByRole("link", { name: "greet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "summarize" })).toBeInTheDocument();
  });

  it("shows the designed empty state when there are no prompts", () => {
    setPrompts({ data: [] });
    renderPage();
    expect(screen.getByText(/no prompts yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new prompt/i })).toBeInTheDocument();
  });

  it("filters the table on search", async () => {
    const user = userEvent.setup();
    setPrompts({ data: [prompt({ name: "greet" }), prompt({ name: "summarize" })] });
    renderPage();

    await user.type(screen.getByPlaceholderText(/search prompts…/i), "summ");

    expect(screen.queryByRole("link", { name: "greet" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "summarize" })).toBeInTheDocument();
  });

  it("shows a no-match empty state when search excludes everything", async () => {
    const user = userEvent.setup();
    setPrompts({ data: [prompt({ name: "greet" })] });
    renderPage();

    await user.type(screen.getByPlaceholderText(/search prompts…/i), "zzz");

    expect(screen.getByText(/no prompts match/i)).toBeInTheDocument();
  });
});
