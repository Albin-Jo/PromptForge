import { describe, expect, it } from "vitest";
import { checkVariableContract, detectVariables } from "./variables";

describe("detectVariables", () => {
  it("extracts distinct {{placeholders}}, tolerating inner whitespace", () => {
    expect(detectVariables("Hi {{name}}, your {{ tone }} {{name}}")).toEqual(["name", "tone"]);
  });

  it("ignores non-identifier braces (dots, calls, filters)", () => {
    expect(detectVariables("{{a.b}} {{fn()}} {{1x}} {{}}")).toEqual([]);
  });

  it("returns nothing for plain text", () => {
    expect(detectVariables("no variables here")).toEqual([]);
  });
});

describe("checkVariableContract", () => {
  it("is satisfied when declared exactly matches the body placeholders", () => {
    const c = checkVariableContract("Summarize {{text}} in a {{tone}} tone", ["text", "tone"], []);
    expect(c.undeclared).toEqual([]);
    expect(c.unused).toEqual([]);
    expect(c.required).toEqual(["text", "tone"]);
  });

  it("flags a body placeholder that isn't declared", () => {
    const c = checkVariableContract("Use {{text}} and {{tone}}", ["text"], []);
    expect(c.undeclared).toEqual(["tone"]);
    expect(c.unused).toEqual([]);
  });

  it("flags a declared variable that nothing uses", () => {
    const c = checkVariableContract("Use {{text}}", ["text", "extra"], []);
    expect(c.undeclared).toEqual([]);
    expect(c.unused).toEqual(["extra"]);
  });

  it("counts block-contributed variables as required (no longer 'unused')", () => {
    // `style` comes from a composed block, not the body — declaring it must be valid.
    const c = checkVariableContract("Use {{text}}", ["text", "style"], ["style"]);
    expect(c.undeclared).toEqual([]);
    expect(c.unused).toEqual([]);
    expect(c.required).toEqual(["style", "text"]);
  });

  it("flags a block-required variable that isn't declared", () => {
    const c = checkVariableContract("Use {{text}}", ["text"], ["style"]);
    expect(c.undeclared).toEqual(["style"]);
  });
});
