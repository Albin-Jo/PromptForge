import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { PromptEditorPage } from "./PromptEditorPage";
import { useCreatePrompt, useCreateVersion, usePrompt } from "../lib/prompts/api";
import { toast } from "../lib/toast";

vi.mock("../lib/prompts/api", () => ({
  useCreatePrompt: vi.fn(),
  useCreateVersion: vi.fn(),
  usePrompt: vi.fn(),
}));
// The form renders CompositionEditor, which fetches the block catalog.
vi.mock("../lib/blocks/api", () => ({
  useBlocks: () => ({ data: [], isPending: false, isError: false, error: null }),
  useBlockImpact: () => ({ data: undefined, isFetching: false, isError: false }),
}));
vi.mock("../lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  toastError: vi.fn(),
}));

const mockedCreatePrompt = vi.mocked(useCreatePrompt);
const mockedCreateVersion = vi.mocked(useCreateVersion);
const mockedUsePrompt = vi.mocked(usePrompt);

beforeEach(() => {
  vi.clearAllMocks();
  // Create mode: no name param, so usePrompt is disabled and returns idle.
  mockedUsePrompt.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof usePrompt>);
  mockedCreateVersion.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof useCreateVersion>);
});

function renderCreatePage() {
  return render(
    <MemoryRouter initialEntries={["/prompts/new"]}>
      <Routes>
        <Route path="/prompts/new" element={<PromptEditorPage />} />
        <Route path="/prompts" element={<div>prompt list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PromptEditorPage", () => {
  it("fires a success toast when a prompt is created", async () => {
    // mutate immediately resolves via its onSuccess callback with the created prompt.
    const mutate = vi.fn((_body, opts) => opts?.onSuccess?.({ name: "summarize" }));
    mockedCreatePrompt.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useCreatePrompt>);

    const user = userEvent.setup();
    renderCreatePage();

    await user.type(screen.getByLabelText(/name/i), "summarize");
    await user.type(screen.getByLabelText(/content/i), "Summarize {{text}}");
    await user.click(screen.getByRole("button", { name: /create prompt/i }));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("summarize"));
  });

  it("fires an error toast when creation fails", async () => {
    const mutate = vi.fn((_body, opts) => opts?.onError?.(new Error("nope")));
    mockedCreatePrompt.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useCreatePrompt>);

    const user = userEvent.setup();
    renderCreatePage();

    await user.type(screen.getByLabelText(/name/i), "summarize");
    await user.type(screen.getByLabelText(/content/i), "Summarize {{text}}");
    await user.click(screen.getByRole("button", { name: /create prompt/i }));

    expect(toast.error).toHaveBeenCalledTimes(1);
  });
});
