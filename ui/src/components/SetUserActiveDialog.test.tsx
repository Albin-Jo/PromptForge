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
import type { User } from "../lib/users/types";
import { SetUserActiveDialog } from "./SetUserActiveDialog";

const mockedFetch = vi.mocked(apiFetch);

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "bob@example.com",
    role: "editor",
    is_active: true,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function renderDialog(user: User) {
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<SetUserActiveDialog user={user} onOpenChange={onOpenChange} />, { wrapper });
  return { onOpenChange, invalidate };
}

beforeEach(() => vi.clearAllMocks());

describe("SetUserActiveDialog", () => {
  it("PATCHes is_active=false and invalidates the user list on deactivate", async () => {
    mockedFetch.mockResolvedValue(makeUser({ is_active: false }) as never);
    const { onOpenChange, invalidate } = renderDialog(makeUser());

    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));

    await waitFor(() =>
      expect(mockedFetch).toHaveBeenCalledWith("/auth/users/u1", {
        method: "PATCH",
        body: { is_active: false },
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users"] });
    expect(toast.success).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders the reactivate direction for an inactive user", async () => {
    mockedFetch.mockResolvedValue(makeUser({ is_active: true }) as never);
    renderDialog(makeUser({ is_active: false }));

    await userEvent.click(screen.getByRole("button", { name: "Reactivate" }));

    await waitFor(() =>
      expect(mockedFetch).toHaveBeenCalledWith("/auth/users/u1", {
        method: "PATCH",
        body: { is_active: true },
      }),
    );
  });

  it("keeps the dialog open and shows the reason on a 409 self-lockout", async () => {
    const detail = "cannot remove the last active admin";
    mockedFetch.mockRejectedValue(new ApiError(409, detail, { detail }));
    const { onOpenChange } = renderDialog(makeUser({ role: "admin" }));

    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(toastError).not.toHaveBeenCalled();
  });
});
