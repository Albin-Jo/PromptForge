import { describe, expect, it } from "vitest";

import { formatCost, formatMs, formatPct, formatQuality, formatRelative } from "./format";

describe("formatCost", () => {
  it("renders null/absent and non-numeric input as an em dash", () => {
    expect(formatCost(null)).toBe("—");
    expect(formatCost("not-a-number")).toBe("—");
  });

  it("renders an exact zero as $0.00", () => {
    expect(formatCost("0.000000")).toBe("$0.00");
  });

  it("keeps significant digits for sub-cent costs instead of collapsing to $0.00", () => {
    expect(formatCost("0.000450")).toBe("$0.00045");
  });

  it("rounds at the cent without reading low on float-truncated values", () => {
    // 0.015 is stored as 0.01499…; a naive toFixed(2) would yield "$0.01".
    expect(formatCost("0.015000")).toBe("$0.02");
    expect(formatCost("1.005")).toBe("$1.01");
    expect(formatCost("2.50")).toBe("$2.50");
  });
});

describe("formatPct / formatQuality / formatMs", () => {
  it("renders null as an em dash across the formatters", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatQuality(null)).toBe("—");
    expect(formatMs(null)).toBe("—");
  });

  it("formats rates, quality, and latency", () => {
    expect(formatPct(0.021)).toBe("2.1%");
    expect(formatQuality(0.9)).toBe("0.90");
    expect(formatMs(1240.4)).toBe("1,240 ms");
  });
});

describe("formatRelative", () => {
  const now = Date.parse("2026-06-25T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();
  const SEC = 1000;
  const MIN = 60 * SEC;
  const HOUR = 60 * MIN;
  const DAY = 24 * HOUR;

  it("reads very recent times as 'just now'", () => {
    expect(formatRelative(ago(10 * SEC), now)).toBe("just now");
  });

  it("scales the unit and pluralizes", () => {
    expect(formatRelative(ago(MIN), now)).toBe("1 minute ago");
    expect(formatRelative(ago(5 * MIN), now)).toBe("5 minutes ago");
    expect(formatRelative(ago(HOUR), now)).toBe("1 hour ago");
    expect(formatRelative(ago(7 * DAY), now)).toBe("7 days ago");
  });

  it("falls back to the raw string on an unparseable input", () => {
    expect(formatRelative("not-a-date", now)).toBe("not-a-date");
  });

  it("accepts an epoch-ms number (react-query's dataUpdatedAt)", () => {
    expect(formatRelative(now - 5 * MIN, now)).toBe("5 minutes ago");
  });

  it("renders compact wording for the freshness chip, with second granularity", () => {
    expect(formatRelative(now - 12 * SEC, now, "compact")).toBe("12s ago");
    expect(formatRelative(now - 5 * MIN, now, "compact")).toBe("5m ago");
    expect(formatRelative(now - 3 * HOUR, now, "compact")).toBe("3h ago");
    expect(formatRelative(now - 2 * DAY, now, "compact")).toBe("2d ago");
  });
});
