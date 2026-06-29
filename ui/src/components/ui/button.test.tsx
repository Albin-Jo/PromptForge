import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

// Smoke test for the shadcn pipeline: proves the "@/" alias resolves, cva generates classes,
// and the primitive renders. Each core primitive added in task #3 gets one of these.
describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("applies variant + size classes via cva", () => {
    render(
      <Button variant="outline" size="sm">
        Cancel
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "Cancel" });
    expect(btn.className).toContain("border-input");
    expect(btn.className).toContain("h-8");
  });

  it("renders as its child element when asChild is set", () => {
    render(
      <Button asChild>
        <a href="/x">Link</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Link" });
    expect(link).toBeInTheDocument();
    expect(link.className).toContain("bg-primary");
  });
});
