import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TracesPage } from "./TracesPage";
import { usePrompt } from "../lib/prompts/api";

vi.mock("../lib/prompts/api", () => ({ usePrompt: vi.fn() }));
// The list/detail are tested in isolation; assert the page feeds newest-first versions down.
vi.mock("../components/TracesPanel", () => ({
  TracesPanel: ({ name, versions }: { name?: string; versions: number[] }) => (
    <div data-testid="traces-panel">{`${name}:${versions.join(",")}`}</div>
  ),
}));
const mockedUsePrompt = vi.mocked(usePrompt);

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/prompts/greeter/traces"]}>
      <Routes>
        <Route path="prompts/:name/traces" element={<TracesPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("TracesPage", () => {
  it("renders the Traces tab and passes newest-first version numbers to the panel", () => {
    mockedUsePrompt.mockReturnValue({
      isPending: false,
      isError: false,
      error: null,
      data: { versions: [{ version_number: 1 }, { version_number: 3 }, { version_number: 2 }] },
    } as unknown as ReturnType<typeof usePrompt>);

    renderPage();

    expect(screen.getByRole("link", { name: "Traces" })).toBeInTheDocument();
    expect(screen.getByTestId("traces-panel")).toHaveTextContent("greeter:3,2,1");
  });
});
