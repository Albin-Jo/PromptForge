import { describe, expect, it } from "vitest";

import { toCsv } from "./csv";

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
