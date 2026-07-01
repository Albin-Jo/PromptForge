import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

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
import { toast } from "../lib/toast";
import type { User } from "../lib/users/types";
import { EditUserRoleDialog } from "./EditUserRoleDialog";

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
  render(<EditUserRoleDialog user={user} onOpenChange={onOpenChange} />, { wrapper });
  return { onOpenChange, invalidate };
}

beforeEach(() => vi.clearAllMocks());

describe("EditUserRoleDialog", () => {
  it("seeds the select with the user's current role", () => {
    renderDialog(makeUser({ role: "admin" }));
    expect(screen.getByRole("combobox")).toHaveValue("admin");
  });

  it("PATCHes the new role and invalidates the user list on save", async () => {
    mockedFetch.mockResolvedValue(makeUser({ role: "admin" }) as never);
    const { onOpenChange, invalidate } = renderDialog(makeUser({ role: "editor" }));

    await userEvent.selectOptions(screen.getByRole("combobox"), "admin");
    await userEvent.click(screen.getByRole("button", { name: "Save role" }));

    await waitFor(() =>
      expect(mockedFetch).toHaveBeenCalledWith("/auth/users/u1", {
        method: "PATCH",
        body: { role: "admin" },
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users"] });
    expect(toast.success).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("surfaces a 409 self-lockout as a form error and stays open", async () => {
    const detail = "cannot remove the last active admin";
    mockedFetch.mockRejectedValue(new ApiError(409, detail, { detail }));
    const { onOpenChange } = renderDialog(makeUser({ role: "admin" }));

    await userEvent.selectOptions(screen.getByRole("combobox"), "editor");
    await userEvent.click(screen.getByRole("button", { name: "Save role" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
