import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RequireAdmin } from "./RequireAdmin";
import { useCan } from "../lib/auth/AuthContext";
import { toast } from "../lib/toast";

vi.mock("../lib/auth/AuthContext", () => ({ useCan: vi.fn() }));
vi.mock("../lib/toast", () => ({ toast: { error: vi.fn() } }));

const mockedUseCan = vi.mocked(useCan);
const mockedToastError = vi.mocked(toast.error);

// Render RequireAdmin guarding an /admin route, starting there, with a stub home to bounce to.
function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route element={<RequireAdmin />}>
          <Route path="/admin" element={<div>admin body</div>} />
        </Route>
        <Route path="/" element={<div>overview home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAdmin", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the guarded outlet for an admin", () => {
    mockedUseCan.mockReturnValue(true);
    renderGuard();
    expect(screen.getByText("admin body")).toBeInTheDocument();
    expect(mockedToastError).not.toHaveBeenCalled();
  });

  it("bounces a non-admin to the overview with an explanatory toast", () => {
    mockedUseCan.mockReturnValue(false);
    renderGuard();
    expect(screen.getByText("overview home")).toBeInTheDocument();
    expect(screen.queryByText("admin body")).not.toBeInTheDocument();
    expect(mockedToastError).toHaveBeenCalledWith("Admin access required");
  });
});
