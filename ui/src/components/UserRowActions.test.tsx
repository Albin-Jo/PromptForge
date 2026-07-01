import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// The dialogs mount useUpdateUser (react-query) + toast; stub the network + toast so opening
// them doesn't reach out. This test is about the ⋯ menu → correct dialog wiring, not mutations.
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));
vi.mock("../lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  toastError: vi.fn(),
}));

import type { User } from "../lib/users/types";
import { UserRowActions } from "./UserRowActions";

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

function renderActions(user: User) {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<UserRowActions user={user} />, { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("UserRowActions", () => {
  it("opens the Edit role dialog from the ⋯ menu", async () => {
    renderActions(makeUser());

    await userEvent.click(screen.getByRole("button", { name: "Actions for bob@example.com" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Edit role" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent(/Change the role for bob@example.com/);
  });

  it("opens the Deactivate confirm dialog from the ⋯ menu", async () => {
    renderActions(makeUser());

    await userEvent.click(screen.getByRole("button", { name: "Actions for bob@example.com" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Deactivate" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Deactivate user");
  });

  it("labels the status action 'Reactivate' for an inactive user", async () => {
    renderActions(makeUser({ is_active: false }));

    await userEvent.click(screen.getByRole("button", { name: "Actions for bob@example.com" }));

    expect(await screen.findByRole("menuitem", { name: "Reactivate" })).toBeInTheDocument();
  });
});
