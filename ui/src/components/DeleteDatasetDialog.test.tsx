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
vi.mock("../lib/toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { apiFetch } from "../lib/api";
import { toast } from "../lib/toast";
import { DeleteDatasetDialog } from "./DeleteDatasetDialog";

const mockedFetch = vi.mocked(apiFetch);

function renderDialog(onOpenChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<DeleteDatasetDialog dataset="gs" onOpenChange={onOpenChange} />, { wrapper });
  return { onOpenChange };
}

beforeEach(() => vi.clearAllMocks());

describe("DeleteDatasetDialog", () => {
  it("deletes and closes on success", async () => {
    mockedFetch.mockResolvedValue(null as never);
    const { onOpenChange } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mockedFetch).toHaveBeenCalledWith("/datasets/gs", { method: "DELETE" });
    expect(toast.success).toHaveBeenCalled();
  });

  it("keeps the dialog open and shows the in-use prompts on a 409", async () => {
    mockedFetch.mockRejectedValue(
      new ApiError(409, "dataset 'gs' is in use as a golden set by: bar, baz", {
        detail: "dataset 'gs' is in use as a golden set by: bar, baz",
      }),
    );
    const { onOpenChange } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    // The conflict is rendered as state, not a toast — and the dialog stays open.
    expect(await screen.findByText(/in use as a golden set by: bar, baz/)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(toast.error).not.toHaveBeenCalled();
  });
});
