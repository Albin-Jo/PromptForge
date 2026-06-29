import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// CompositionEditor + the page read useBlocks()/useBlock() -> apiFetch; stub the network.
vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {},
  apiFetch: vi.fn(),
}));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: () => true }));
// Keep toast/navigation side effects out of the test.
vi.mock("../lib/toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { apiFetch } from "../lib/api";
import { BlockEditorPage } from "./BlockEditorPage";

const mockedFetch = vi.mocked(apiFetch);

// `outer` v1 composes `inner` v1 — its read carries the pinned ref (the backend read-model fix).
const OUTER = {
  id: "b-outer",
  name: "outer",
  role: "other",
  description: "",
  created_at: "",
  updated_at: "",
  versions: [
    {
      id: "ov1",
      version_number: 1,
      parent_version_id: null,
      content: "OUTER",
      input_variables: ["x"],
      created_at: "",
      blocks: [{ block: "inner", version: 1 }],
    },
  ],
};
const INNER = {
  id: "b-inner",
  name: "inner",
  role: "other",
  description: "",
  created_at: "",
  updated_at: "",
  versions: [
    {
      id: "iv1",
      version_number: 1,
      parent_version_id: null,
      content: "INNER {{x}}",
      input_variables: ["x"],
      created_at: "",
      blocks: [],
    },
  ],
};

function renderNewVersionPage() {
  mockedFetch.mockImplementation((path: string, opts?: { method?: string }) => {
    if (path === "/blocks/outer") return Promise.resolve(OUTER as never);
    if (path === "/blocks") return Promise.resolve([OUTER, INNER] as never);
    if (path === "/blocks/outer/versions" && opts?.method === "POST") {
      return Promise.resolve({ ...OUTER.versions[0], id: "ov2", version_number: 2 } as never);
    }
    return Promise.resolve(null as never);
  });
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/blocks/outer/versions/new"]}>
        <Routes>
          <Route path="/blocks/:name/versions/new" element={<BlockEditorPage />} />
          {/* The page navigates here on save — present so the redirect resolves quietly. */}
          <Route path="/blocks/:name" element={<div>block detail</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("BlockEditorPage — new version", () => {
  // The regression: a new version of a composed block must carry its child-block refs forward,
  // not silently start from an empty composition. We assert the prefill survives all the way to
  // the POST body.
  it("carries the latest version's composition forward into the new-version POST", async () => {
    renderNewVersionPage();

    // Wait for the block to load (the form prefills from its latest version).
    await screen.findByDisplayValue("OUTER");

    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));

    await waitFor(() => {
      const post = mockedFetch.mock.calls.find(
        ([path, opts]) => path === "/blocks/outer/versions" && opts?.method === "POST",
      );
      expect(post).toBeTruthy();
      expect((post![1] as { body: { blocks: unknown } }).body.blocks).toEqual([
        { block: "inner", version: 1 },
      ]);
    });
  });
});
