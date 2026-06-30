import { describe, expect, it } from "vitest";

import { toCsv, fromCsv } from "./csv";

interface Row {
  name: string;
  count: number | null;
  note: string;
}

describe("toCsv", () => {
  const columns = [
    { header: "name", value: (r: Row) => r.name },
    { header: "count", value: (r: Row) => r.count },
    { header: "note", value: (r: Row) => r.note },
  ];

  it("writes a header row then one row per record", () => {
    const csv = toCsv([{ name: "greet", count: 3, note: "ok" }], columns);
    expect(csv).toBe("name,count,note\r\ngreet,3,ok");
  });

  it("renders nullish cells as empty", () => {
    const csv = toCsv([{ name: "x", count: null, note: "" }], columns);
    expect(csv).toBe("name,count,note\r\nx,,");
  });

  it("quotes fields containing commas, quotes, or newlines", () => {
    const csv = toCsv(
      [{ name: 'a,"b"', count: 1, note: "line1\nline2" }],
      columns,
    );
    expect(csv).toBe('name,count,note\r\n"a,""b""",1,"line1\nline2"');
  });

  it("handles an empty row set (header only)", () => {
    expect(toCsv([], columns)).toBe("name,count,note");
  });
});

describe("fromCsv", () => {
  it("parses a simple input-only CSV", () => {
    const result = fromCsv("input\nHello\nWorld");
    expect(result.errors).toHaveLength(0);
    expect(result.rows).toEqual([
      { input: "Hello", reference: null },
      { input: "World", reference: null },
    ]);
  });

  it("parses input + reference columns", () => {
    const result = fromCsv("input,reference\nTell me a joke,A funny joke");
    expect(result.errors).toHaveLength(0);
    expect(result.rows[0]).toEqual({ input: "Tell me a joke", reference: "A funny joke" });
  });

  it("treats an empty reference cell as null (optional column absent)", () => {
    const result = fromCsv("input,reference\nHello,");
    expect(result.rows[0].reference).toBeNull();
  });

  it("returns null reference when reference column is missing from headers", () => {
    const result = fromCsv("input\nHello");
    expect(result.rows[0].reference).toBeNull();
  });

  it("accepts a custom reference column header", () => {
    const result = fromCsv("input,expected_output\nQ,A", "expected_output");
    expect(result.rows[0]).toEqual({ input: "Q", reference: "A" });
  });

  it("handles quoted fields containing commas", () => {
    const result = fromCsv('input,reference\n"Hello, world","Yes, that works"');
    expect(result.rows[0]).toEqual({ input: "Hello, world", reference: "Yes, that works" });
  });

  it("handles doubled-quote escapes inside quoted fields", () => {
    const result = fromCsv('input\n"He said ""hi"""');
    expect(result.rows[0].input).toBe('He said "hi"');
  });

  it("handles CRLF line endings", () => {
    const result = fromCsv("input,reference\r\nfoo,bar\r\nbaz,qux");
    expect(result.rows).toHaveLength(2);
    expect(result.rows[1]).toEqual({ input: "baz", reference: "qux" });
  });

  it("skips rows with an empty input and records an error", () => {
    const result = fromCsv("input\nHello\n\nWorld");
    expect(result.rows).toHaveLength(2);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].message).toMatch(/empty/i);
  });

  it("returns an error and no rows when the input column is absent", () => {
    const result = fromCsv("question,answer\nQ,A");
    expect(result.rows).toHaveLength(0);
    expect(result.errors[0].message).toMatch(/Required column "input"/);
  });

  it("returns empty rows and no errors for an empty string", () => {
    const result = fromCsv("");
    expect(result.rows).toHaveLength(0);
    expect(result.errors).toHaveLength(0);
  });
});
