import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DiffView } from "./DiffView";

describe("DiffView", () => {
  it("renders a 'no differences' message for identical text", () => {
    render(<DiffView oldText={"same\ntext"} newText={"same\ntext"} oldLabel="v1" newLabel="v2" />);
    expect(screen.getByText(/no differences/i)).toBeInTheDocument();
  });

  it("renders added and removed rows with the right diff types", () => {
    const { container } = render(
      <DiffView oldText={"keep\nold"} newText={"keep\nnew"} oldLabel="v1" newLabel="v2" />,
    );
    const removed = container.querySelectorAll('[data-diff-type="removed"]');
    const added = container.querySelectorAll('[data-diff-type="added"]');
    const context = container.querySelectorAll('[data-diff-type="context"]');

    expect(context).toHaveLength(1);
    expect(removed).toHaveLength(1);
    expect(added).toHaveLength(1);
    expect(removed[0].textContent).toContain("old");
    expect(added[0].textContent).toContain("new");
  });

  it("colors the +/- gutter so the cue survives a faint row tint (dark mode)", () => {
    const { container } = render(<DiffView oldText="old" newText="new" />);
    expect(container.querySelector('[data-diff-type="added"] .text-success')).not.toBeNull();
    expect(container.querySelector('[data-diff-type="removed"] .text-destructive')).not.toBeNull();
  });

  it("wraps long content rather than clipping it", () => {
    const { container } = render(<DiffView oldText="a" newText={"x".repeat(400)} />);
    const cell = container.querySelector('[data-diff-type="added"] .whitespace-pre-wrap');
    expect(cell).not.toBeNull();
    expect(cell?.className).toContain("break-words");
  });

  it("shows the version labels in the header", () => {
    render(<DiffView oldText="a" newText="b" oldLabel="v3" newLabel="v4" />);
    expect(screen.getByText(/v3/)).toBeInTheDocument();
    expect(screen.getByText(/v4/)).toBeInTheDocument();
  });
});
