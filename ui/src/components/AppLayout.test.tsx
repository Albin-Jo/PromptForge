import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "./AppLayout";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";
import { useAuth } from "@/lib/auth/AuthContext";

// Control auth state directly (mirrors RequireAuth.test) and keep the palette's list hooks off
// the network — these are the seams AppLayout/TopBar/CommandPalette consume. The palette now also
// reads useCan (create-verb gate) and the block/dataset lists, so stub those too.
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: vi.fn(), useCan: () => false }));
vi.mock("@/lib/prompts/api", () => ({ usePrompts: () => ({ data: [] }) }));
vi.mock("@/lib/blocks/api", () => ({ useBlocks: () => ({ data: [] }) }));
vi.mock("@/lib/datasets/api", () => ({ useDatasets: () => ({ data: [] }) }));

const baseAuth = {
  user: { email: "dev@example.com" },
  isAuthenticated: true,
  isRestoring: false,
  login: vi.fn(),
  logout: vi.fn(),
};

beforeEach(() => {
  localStorage.clear();
  vi.mocked(useAuth).mockReturnValue(baseAuth as unknown as ReturnType<typeof useAuth>);
});

function renderShell() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<div>home body</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const PALETTE_INPUT = /type a command/i;

describe("AppLayout — command palette opening", () => {
  it("opens on Ctrl/⌘-K and toggles closed again", async () => {
    renderShell();
    expect(screen.queryByPlaceholderText(PALETTE_INPUT)).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(screen.getByPlaceholderText(PALETTE_INPUT)).toBeInTheDocument();

    // Same shortcut toggles it back closed.
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    await waitFor(() =>
      expect(screen.queryByPlaceholderText(PALETTE_INPUT)).not.toBeInTheDocument(),
    );
  });

  it("opens from the top-bar search trigger", () => {
    renderShell();
    // The desktop pill is the first of the (pill + mobile-icon) search buttons.
    const searchButtons = screen.getAllByRole("button", { name: /search/i });
    fireEvent.click(searchButtons[0]);
    expect(screen.getByPlaceholderText(PALETTE_INPUT)).toBeInTheDocument();
  });
});

describe("AppLayout — admin-only nav gating", () => {
  it("hides the Users entry from a non-admin", () => {
    // baseAuth's user has no admin role → the admin-only Users entry must not render.
    renderShell();
    expect(screen.queryByRole("link", { name: /users/i })).not.toBeInTheDocument();
  });

  it("shows the Users entry to an admin", () => {
    vi.mocked(useAuth).mockReturnValue({
      ...baseAuth,
      user: { email: "admin@example.com", role: "admin" },
    } as unknown as ReturnType<typeof useAuth>);
    renderShell();
    expect(screen.getByRole("link", { name: /users/i })).toBeInTheDocument();
  });

  it("shows the current user's email and role in the user menu", async () => {
    vi.mocked(useAuth).mockReturnValue({
      ...baseAuth,
      user: { email: "admin@example.com", role: "admin" },
    } as unknown as ReturnType<typeof useAuth>);
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: /user menu/i }));
    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });
});

describe("AppLayout — sidebar collapse persistence", () => {
  it("persists the collapse choice to localStorage and restores it on remount", () => {
    const { unmount } = renderShell();

    // Defaults expanded; the mount effect has written the initial value.
    expect(screen.getByRole("button", { name: /collapse sidebar/i })).toBeInTheDocument();
    expect(localStorage.getItem("pf-sidebar-collapsed")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
    expect(localStorage.getItem("pf-sidebar-collapsed")).toBe("true");
    expect(screen.getByRole("button", { name: /expand sidebar/i })).toBeInTheDocument();

    // Remount = a fresh page load; the persisted "collapsed" state should survive.
    unmount();
    renderShell();
    expect(screen.getByRole("button", { name: /expand sidebar/i })).toBeInTheDocument();
  });
});
