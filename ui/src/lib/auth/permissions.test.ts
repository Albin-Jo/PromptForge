import { describe, expect, it } from "vitest";
import { roleSatisfies } from "./permissions";

describe("roleSatisfies", () => {
  it("admin satisfies both editor and admin bars (hierarchical)", () => {
    expect(roleSatisfies("admin", "editor")).toBe(true);
    expect(roleSatisfies("admin", "admin")).toBe(true);
  });

  it("editor satisfies the editor bar but not admin", () => {
    expect(roleSatisfies("editor", "editor")).toBe(true);
    expect(roleSatisfies("editor", "admin")).toBe(false);
  });

  it("fails closed for unknown, undefined, or empty roles", () => {
    expect(roleSatisfies(undefined, "editor")).toBe(false);
    expect(roleSatisfies("viewer", "editor")).toBe(false);
    expect(roleSatisfies("", "admin")).toBe(false);
  });
});
