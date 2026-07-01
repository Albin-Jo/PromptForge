import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));
vi.mock("../lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  toastError: vi.fn(),
}));

import { apiFetch } from "../lib/api";
import type { User } from "../lib/users/types";
import { UsersPage } from "./UsersPage";

const mockedFetch = vi.mocked(apiFetch);

function user(overrides: Partial<User>): User {
  return {
    id: "x",
    email: "x@example.com",
    role: "editor",
    is_active: true,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<UsersPage />, { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("UsersPage", () => {
  it("marks a deactivated user with an Inactive badge and a muted row", async () => {
    mockedFetch.mockResolvedValue([
      user({ id: "1", email: "active@example.com", role: "admin", is_active: true }),
      user({ id: "2", email: "gone@example.com", role: "editor", is_active: false }),
    ] as never);

    renderPage();

    const inactiveRow = (await screen.findByText("gone@example.com")).closest("tr");
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(inactiveRow).toHaveClass("opacity-60");

    // The active user reads as active and its row is not muted.
    const activeRow = screen.getByText("active@example.com").closest("tr");
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(activeRow).not.toHaveClass("opacity-60");
  });
});
