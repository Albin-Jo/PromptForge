import { describe, expect, it } from "vitest";
import { diffLines, isUnchanged } from "./diff";

describe("diffLines", () => {
  it("treats identical text as all context", () => {
    const lines = diffLines("a\nb\nc", "a\nb\nc");
    expect(lines.map((l) => l.type)).toEqual(["context", "context", "context"]);
    expect(isUnchanged(lines)).toBe(true);
  });

  it("marks an inserted line as added and renumbers the new side", () => {
    const lines = diffLines("a\nc", "a\nb\nc");
    expect(lines.map((l) => `${l.type}:${l.text}`)).toEqual([
      "context:a",
      "added:b",
      "context:c",
    ]);
    const added = lines.find((l) => l.type === "added");
    expect(added?.oldNumber).toBeNull();
    expect(added?.newNumber).toBe(2);
  });

  it("marks a deleted line as removed", () => {
    const lines = diffLines("a\nb\nc", "a\nc");
    expect(lines.map((l) => `${l.type}:${l.text}`)).toEqual([
      "context:a",
      "removed:b",
      "context:c",
    ]);
  });

  it("represents a changed line as a remove + add pair", () => {
    const lines = diffLines("hello world", "hello there");
    expect(lines.map((l) => l.type)).toEqual(["removed", "added"]);
    expect(isUnchanged(lines)).toBe(false);
  });

  it("treats empty old text as pure additions (no phantom blank line)", () => {
    const lines = diffLines("", "x\ny");
    expect(lines.map((l) => l.type)).toEqual(["added", "added"]);
    expect(lines.map((l) => l.newNumber)).toEqual([1, 2]);
  });

  it("keeps old-side line numbers correct across a deletion", () => {
    const lines = diffLines("a\nb\nc", "a\nc");
    const c = lines.find((l) => l.text === "c");
    expect(c?.oldNumber).toBe(3);
    expect(c?.newNumber).toBe(2);
  });
});
