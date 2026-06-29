import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./RequireAuth";
import { useAuth } from "../lib/auth/AuthContext";

// The guard's only job: given auth state, render the child or redirect to /login.
// Mock useAuth so the test controls that state directly (Task 7 decision).
vi.mock("../lib/auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/" element={<div>protected home</div>} />
        </Route>
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const base = { user: null, isAuthenticated: false, isRestoring: false, login: vi.fn(), logout: vi.fn() };

describe("RequireAuth", () => {
  it("redirects an unauthenticated user to /login", () => {
    mockedUseAuth.mockReturnValue({ ...base, isAuthenticated: false });
    renderAt("/");
    expect(screen.getByText("login page")).toBeInTheDocument();
    expect(screen.queryByText("protected home")).not.toBeInTheDocument();
  });

  it("renders the protected content when authenticated", () => {
    mockedUseAuth.mockReturnValue({ ...base, isAuthenticated: true });
    renderAt("/");
    expect(screen.getByText("protected home")).toBeInTheDocument();
    expect(screen.queryByText("login page")).not.toBeInTheDocument();
  });

  it("shows a loading state (no redirect) while the session is being restored", () => {
    mockedUseAuth.mockReturnValue({ ...base, isRestoring: true });
    renderAt("/");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByText("login page")).not.toBeInTheDocument();
    expect(screen.queryByText("protected home")).not.toBeInTheDocument();
  });
});
