import { describe, expect, it } from "vitest";
import { createSseParser, parseSseFrame } from "./sse";

describe("parseSseFrame", () => {
  it("parses an event name and JSON data", () => {
    const ev = parseSseFrame('event: token\ndata: {"content":"Hi"}');
    expect(ev).toEqual({ event: "token", data: { content: "Hi" } });
  });

  it("defaults the event name to 'message' when omitted", () => {
    const ev = parseSseFrame('data: {"x":1}');
    expect(ev?.event).toBe("message");
  });

  it("keeps non-JSON data as a raw string", () => {
    const ev = parseSseFrame("data: plain text");
    expect(ev?.data).toBe("plain text");
  });

  it("returns null for a frame with no data line", () => {
    expect(parseSseFrame("event: ping")).toBeNull();
  });
});

describe("createSseParser", () => {
  it("emits events as complete frames arrive", () => {
    const parser = createSseParser();
    const events = parser.push('event: token\ndata: {"content":"a"}\n\nevent: done\ndata: {}\n\n');
    expect(events.map((e) => e.event)).toEqual(["token", "done"]);
  });

  it("buffers a frame split across two chunks", () => {
    const parser = createSseParser();
    // First chunk ends mid-frame -> nothing emitted yet.
    expect(parser.push('event: token\ndata: {"con')).toEqual([]);
    // Second chunk completes it.
    const events = parser.push('tent":"He"}\n\n');
    expect(events).toEqual([{ event: "token", data: { content: "He" } }]);
  });

  it("parses an error event", () => {
    const parser = createSseParser();
    const events = parser.push('event: error\ndata: {"type":"GatewayError","detail":"boom"}\n\n');
    expect(events[0]).toEqual({
      event: "error",
      data: { type: "GatewayError", detail: "boom" },
    });
  });
});
