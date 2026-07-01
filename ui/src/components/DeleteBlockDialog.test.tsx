import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Keep the real ApiError so the 409 classifier works; stub only the network call.
import { ApiError } from "../lib/api";
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));
vi.mock("../lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  toastError: vi.fn(),
}));

import { apiFetch } from "../lib/api";
import { toast, toastError } from "../lib/toast";
import { DeleteBlockDialog } from "./DeleteBlockDialog";

const mockedFetch = vi.mocked(apiFetch);

function renderDialog() {
  const onOpenChange = vi.fn();
  const onDeleted = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <DeleteBlockDialog block="guardrails" onOpenChange={onOpenChange} onDeleted={onDeleted} />,
    { wrapper },
  );
  return { onOpenChange, onDeleted };
}

beforeEach(() => vi.clearAllMocks());

describe("DeleteBlockDialog", () => {
  it("deletes and signals onDeleted on success", async () => {
    mockedFetch.mockResolvedValue(null as never);
    const { onDeleted } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(mockedFetch).toHaveBeenCalledWith("/blocks/guardrails", { method: "DELETE" });
    expect(toast.success).toHaveBeenCalled();
  });

  it("keeps the dialog open and names the in-use dependents on a 409", async () => {
    const detail =
      "block 'guardrails' is in use by prompts: support-bot v4; blocks: safety-wrapper v2; " +
      "detach those references first";
    mockedFetch.mockRejectedValue(new ApiError(409, detail, { detail }));
    const { onDeleted } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    // The conflict is rendered as state, not a toast — and the dialog stays open.
    expect(
      await screen.findByText(/in use by prompts: support-bot v4; blocks: safety-wrapper v2/),
    ).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });
});
