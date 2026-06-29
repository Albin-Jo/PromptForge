import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/shell/CommandPalette";

// Isolate the palette from the network: the list hooks return fixed data (the palette reuses the
// same cached list hooks the pages use, so stubbing them is exactly the seam it consumes).
vi.mock("@/lib/prompts/api", () => ({
  usePrompts: () => ({
    data: [
      { name: "greeting" },
      { name: "summarizer" },
    ],
  }),
}));
vi.mock("@/lib/blocks/api", () => ({
  useBlocks: () => ({ data: [{ name: "intro-block" }] }),
}));
vi.mock("@/lib/datasets/api", () => ({
  useDatasets: () => ({ data: [{ name: "qa-set" }] }),
}));

// Role gate is a hoisted, mutable flag so one test can flip the palette to a viewer.
const auth = vi.hoisted(() => ({ canCreate: true }));
vi.mock("@/lib/auth/AuthContext", () => ({ useCan: () => auth.canCreate }));

beforeEach(() => {
  auth.canCreate = true;
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

// Harness with real open state so onOpenChange(false) actually closes the dialog.
function Harness({ initialOpen = true }: { initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen);
  return (
    <MemoryRouter initialEntries={["/"]}>
      <CommandPalette open={open} onOpenChange={setOpen} />
      <LocationProbe />
    </MemoryRouter>
  );
}

describe("CommandPalette", () => {
  it("renders nothing when closed", () => {
    render(<Harness initialOpen={false} />);
    expect(screen.queryByPlaceholderText(/type a command/i)).not.toBeInTheDocument();
  });

  it("opens and shows navigation + create + jump groups for an editor", () => {
    render(<Harness />);
    expect(screen.getByPlaceholderText(/type a command/i)).toBeInTheDocument();
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByText("Prompts")).toBeInTheDocument();
    // Create verbs (editor+).
    expect(screen.getByText("New prompt")).toBeInTheDocument();
    expect(screen.getByText("New block")).toBeInTheDocument();
    expect(screen.getByText("New golden set")).toBeInTheDocument();
    // Jump-to groups for each entity.
    expect(screen.getByText("greeting")).toBeInTheDocument();
    expect(screen.getByText("summarizer")).toBeInTheDocument();
    expect(screen.getByText("intro-block")).toBeInTheDocument();
    expect(screen.getByText("qa-set")).toBeInTheDocument();
  });

  it("hides create verbs from a viewer but keeps jump-to groups", () => {
    auth.canCreate = false;
    render(<Harness />);
    expect(screen.queryByText("New prompt")).not.toBeInTheDocument();
    expect(screen.queryByText("New block")).not.toBeInTheDocument();
    expect(screen.queryByText("New golden set")).not.toBeInTheDocument();
    // Read-only jump-to navigation stays available.
    expect(screen.getByText("greeting")).toBeInTheDocument();
    expect(screen.getByText("intro-block")).toBeInTheDocument();
    expect(screen.getByText("qa-set")).toBeInTheDocument();
  });

  it("jumps to a block detail page and closes", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("intro-block"));
    expect(screen.getByTestId("location")).toHaveTextContent("/blocks/intro-block");
  });

  it("jumps to a golden-set edit page and closes", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("qa-set"));
    expect(screen.getByTestId("location")).toHaveTextContent("/datasets/qa-set/edit");
  });

  it("filters items by the typed query", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByPlaceholderText(/type a command/i), "greet");
    expect(screen.getByText("greeting")).toBeInTheDocument();
    expect(screen.queryByText("summarizer")).not.toBeInTheDocument();
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
  });

  it("navigates and closes when an item is selected", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("summarizer"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/prompts/summarizer/edit",
    );
    // onOpenChange(false) ran -> dialog gone.
    expect(screen.queryByPlaceholderText(/type a command/i)).not.toBeInTheDocument();
  });
});
