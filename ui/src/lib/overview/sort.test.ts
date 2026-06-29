import { describe, expect, it } from "vitest";

import { sortPrompts } from "./sort";
import type { PromptRollup } from "./types";

function rollup(overrides: Partial<PromptRollup> = {}): PromptRollup {
  return {
    name: "p",
    latest_version: 1,
    request_count: 0,
    error_rate: null,
    p95_ms: null,
    cost_usd: null,
    quality: null,
    attention: [],
    ...overrides,
  };
}

const names = (rows: PromptRollup[]) => rows.map((r) => r.name);

describe("sortPrompts", () => {
  it("sorts a numeric column descending", () => {
    const rows = [
      rollup({ name: "a", request_count: 5 }),
      rollup({ name: "b", request_count: 50 }),
      rollup({ name: "c", request_count: 1 }),
    ];
    expect(names(sortPrompts(rows, { key: "request_count", dir: "desc" }))).toEqual(["b", "a", "c"]);
  });

  it("sorts a numeric column ascending", () => {
    const rows = [
      rollup({ name: "a", request_count: 5 }),
      rollup({ name: "b", request_count: 50 }),
    ];
    expect(names(sortPrompts(rows, { key: "request_count", dir: "asc" }))).toEqual(["a", "b"]);
  });

  it("orders the exact-decimal cost string numerically, not lexically", () => {
    const rows = [
      rollup({ name: "a", cost_usd: "9.000000" }),
      rollup({ name: "b", cost_usd: "10.000000" }),
    ];
    // Lexical order would put "10" before "9"; numeric desc must put 10 first.
    expect(names(sortPrompts(rows, { key: "cost_usd", dir: "desc" }))).toEqual(["b", "a"]);
  });

  it("sinks null metrics to the bottom of a desc sort", () => {
    const rows = [
      rollup({ name: "a", quality: null }),
      rollup({ name: "b", quality: 0.9 }),
    ];
    expect(names(sortPrompts(rows, { key: "quality", dir: "desc" }))).toEqual(["b", "a"]);
  });

  it("breaks ties by name deterministically when the metric is equal or both null", () => {
    const rows = [
      rollup({ name: "charlie", request_count: 10 }),
      rollup({ name: "alpha", request_count: 10 }),
      rollup({ name: "bravo", request_count: 10 }),
    ];
    // Equal metric → name-ascending tiebreak regardless of sort direction.
    expect(names(sortPrompts(rows, { key: "request_count", dir: "desc" }))).toEqual([
      "alpha",
      "bravo",
      "charlie",
    ]);
    // Two null metrics must not jitter (the old av-bv subtraction produced NaN here).
    const allNull = [rollup({ name: "z" }), rollup({ name: "y" }), rollup({ name: "x" })];
    expect(names(sortPrompts(allNull, { key: "p95_ms", dir: "desc" }))).toEqual(["x", "y", "z"]);
  });

  it("does not mutate the input array", () => {
    const rows = [rollup({ name: "b" }), rollup({ name: "a" })];
    sortPrompts(rows, { key: "name", dir: "asc" });
    expect(names(rows)).toEqual(["b", "a"]);
  });
});
