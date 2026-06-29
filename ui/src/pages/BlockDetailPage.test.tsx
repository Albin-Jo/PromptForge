import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";

vi.mock("../lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => true }));

import { apiFetch } from "../lib/api";
import { BlockDetailPage } from "./BlockDetailPage";

const mockedFetch = vi.mocked(apiFetch);

const BLOCK = {
  id: "b1",
  name: "greeting",
  role: "guardrails",
  description: "the house style",
  created_at: "",
  updated_at: "",
  // Deliberately oldest-first, to prove the page re-sorts newest-first.
  versions: [
    { id: "v1", version_number: 1, parent_version_id: null, content: "ALPHA", input_variables: [], created_at: "" },
    { id: "v2", version_number: 2, parent_version_id: "v1", content: "BETA", input_variables: ["tone"], created_at: "" },
  ],
};

const IMPACT = { block: "greeting", prompts: [{ name: "summarize", version_number: 3 }], blocks: [] };

function renderPage() {
  mockedFetch.mockImplementation((path: string) => {
    if (path === "/blocks/greeting") return Promise.resolve(BLOCK as never);
    if (path === "/blocks/greeting/impact") return Promise.resolve(IMPACT as never);
    return Promise.resolve(null as never);
  });
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/blocks/greeting"]}>
        <Routes>
          <Route path="/blocks/:name" element={children} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  render(<BlockDetailPage />, { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("BlockDetailPage", () => {
  it("renders version history newest-first", async () => {
    renderPage();
    const beta = await screen.findByText("BETA");
    const alpha = screen.getByText("ALPHA");
    // ALPHA (v1) must appear *after* BETA (v2) in document order.
    expect(beta.compareDocumentPosition(alpha) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the impact summary and the new-version action", async () => {
    renderPage();
    expect(
      await screen.findByText(/Used by 1 prompt version and 0 block versions\./),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "New version" })).toBeInTheDocument(),
    );
  });
});
