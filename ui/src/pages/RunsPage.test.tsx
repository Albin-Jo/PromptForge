import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RunsPage } from "./RunsPage";

// The run-history lists are tested in isolation; here we only assert the page wires the route
// params (name + version) into both of them and titles itself for the version.
vi.mock("../components/EvalRunsList", () => ({
  EvalRunsList: ({ name, versionNumber }: { name?: string; versionNumber?: number }) => (
    <div data-testid="eval-runs">{`${name}:${versionNumber}`}</div>
  ),
}));
vi.mock("../components/ScanRunsList", () => ({
  ScanRunsList: ({ name, versionNumber }: { name?: string; versionNumber?: number }) => (
    <div data-testid="scan-runs">{`${name}:${versionNumber}`}</div>
  ),
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="prompts/:name/versions/:versionNumber/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunsPage", () => {
  it("titles for the version and passes name + version into both run lists", () => {
    renderAt("/prompts/greeter/versions/3/runs");

    expect(screen.getByRole("heading", { name: /greeter — v3 runs/i })).toBeInTheDocument();
    expect(screen.getByTestId("eval-runs")).toHaveTextContent("greeter:3");
    expect(screen.getByTestId("scan-runs")).toHaveTextContent("greeter:3");
  });
});
