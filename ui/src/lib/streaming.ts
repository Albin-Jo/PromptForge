// Streaming client for the gateway's POST /complete endpoint (Sprint 15, Task 3).
//
// POSTs the messages + model config, then reads the SSE stream off the response body
// and turns each frame into a handler callback: `token` deltas append, `done` ends the
// stream, `error` (which rides the stream because headers are already sent) reports a
// provider failure. Abortable via an AbortSignal so the UI can offer a Stop button.

import { API_BASE_URL } from "./api";
import { createSseParser } from "./sse";

export interface CompletionMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** Mirrors the gateway's ModelConfig: `model` is required, the rest are optional knobs. */
export interface CompletionConfig {
  model: string;
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stop?: string[];
  presence_penalty?: number;
  frequency_penalty?: number;
  seed?: number;
}

export interface StreamHandlers {
  onToken: (content: string) => void;
  onDone: () => void;
  onError: (detail: string) => void;
}

export interface CompletionRequestBody {
  messages: CompletionMessage[];
  config: CompletionConfig;
}

/**
 * Turn a non-2xx status from /complete into an actionable message. These statuses arrive
 * on the response *before* the stream opens (auth, rate limit, gateway timeout), so they
 * never reach the in-stream `error` event — we map them here. Unmapped statuses keep the
 * raw number so an unexpected failure is still diagnosable.
 */
export function messageForStatus(status: number): string {
  switch (status) {
    case 429:
      return "Rate limited — wait a moment and retry.";
    case 401:
    case 403:
      return "Authentication problem — check the gateway's provider API key.";
    case 408:
    case 504:
      return "The model took too long to respond. Try again.";
    default:
      return `Stream failed (HTTP ${status}).`;
  }
}

/** Stream a completion, invoking handlers as SSE events arrive. Resolves when the stream ends. */
export async function streamCompletion(
  body: CompletionRequestBody,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    // No Authorization header: the gateway's /complete carries no auth dependency today,
    // and we can't route through apiFetch (it parses JSON, not a stream) so we don't get
    // its 401-refresh either. If /complete is ever put behind auth, this call must grow a
    // Bearer header + refresh handling (see ADR 0020).
    response = await fetch(`${API_BASE_URL}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError("Could not reach the API.");
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError(messageForStatus(response.status));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) {
        if (event.event === "token") {
          handlers.onToken((event.data as { content?: string }).content ?? "");
        } else if (event.event === "done") {
          handlers.onDone();
          return;
        } else if (event.event === "error") {
          handlers.onError((event.data as { detail?: string }).detail ?? "Stream error.");
          return;
        }
      }
    }
  } catch (err) {
    // A user-initiated abort is expected, not an error.
    if ((err as Error).name !== "AbortError") {
      handlers.onError("The stream was interrupted.");
    }
  } finally {
    // Close the stream deterministically on every exit (done, error, abort) rather than
    // leaving a locked reader for GC. cancel() also releases the lock; it can reject on an
    // already-aborted reader, so swallow that.
    await reader.cancel().catch(() => {});
  }
}
