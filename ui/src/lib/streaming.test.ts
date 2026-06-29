import { afterEach, describe, expect, it, vi } from "vitest";
import { streamCompletion, type StreamHandlers } from "./streaming";

// Build a Response whose body is a real ReadableStream of the given text chunks, so the
// test exercises the actual getReader()/TextDecoder/parser loop — not a mock of it.
function streamResponse(chunks: string[], init?: ResponseInit): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, ...init });
}

function handlers() {
  return {
    onToken: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  } satisfies StreamHandlers;
}

const body = { messages: [], config: { model: "openai/gpt-4o-mini" } };

afterEach(() => {
  vi.restoreAllMocks();
});

describe("streamCompletion", () => {
  it("dispatches token deltas in order then done", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse([
          'event: token\ndata: {"content":"He"}\n\n',
          'event: token\ndata: {"content":"llo"}\n\n',
          "event: done\ndata: {}\n\n",
        ]),
      ),
    );
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onToken.mock.calls.map((c) => c[0])).toEqual(["He", "llo"]);
    expect(h.onDone).toHaveBeenCalledOnce();
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("reassembles a frame split across two network chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse(['event: token\ndata: {"con', 'tent":"X"}\n\nevent: done\ndata: {}\n\n']),
      ),
    );
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onToken).toHaveBeenCalledExactlyOnceWith("X");
    expect(h.onDone).toHaveBeenCalledOnce();
  });

  it("reports an error event and stops (no done)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse([
          'event: error\ndata: {"type":"GatewayError","detail":"boom"}\n\n',
          "event: done\ndata: {}\n\n",
        ]),
      ),
    );
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onError).toHaveBeenCalledExactlyOnceWith("boom");
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("reports a non-2xx response as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("nope", { status: 500 })),
    );
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onError).toHaveBeenCalledOnce();
    expect(h.onError.mock.calls[0][0]).toContain("500");
    expect(h.onToken).not.toHaveBeenCalled();
  });

  it("treats a user abort as a non-error (silent)", async () => {
    const abortErr = Object.assign(new Error("aborted"), { name: "AbortError" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortErr));
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("reports a network failure (non-abort) as an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const h = handlers();
    await streamCompletion(body, h);

    expect(h.onError).toHaveBeenCalledOnce();
    expect(h.onError.mock.calls[0][0]).toMatch(/could not reach/i);
  });
});
