// A tiny Server-Sent Events parser (Sprint 15, Task 3).
//
// We can't use the browser's native EventSource: it's GET-only and can't set headers,
// but our /complete endpoint is a POST with a JSON body. So we read the response body
// as a stream ourselves and parse the SSE wire format here.
//
// The wire format (one frame per event, frames separated by a blank line):
//   event: token\n
//   data: {"content":"He"}\n
//   \n
// Network chunks don't align to frame boundaries, so the parser buffers across pushes
// and only emits frames once their terminating blank line has arrived.

export interface SseEvent {
  /** The `event:` name; defaults to "message" if the frame omits one (SSE spec). */
  event: string;
  /** The `data:` payload, JSON-parsed when possible, otherwise the raw string. */
  data: unknown;
}

/** Parse one complete frame (the text between blank lines) into an event, or null if empty. */
export function parseSseFrame(frame: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
    // Comment lines (":...") and unknown fields are ignored, per the SSE spec.
  }
  if (dataLines.length === 0) return null;

  const raw = dataLines.join("\n");
  let data: unknown = raw;
  try {
    data = JSON.parse(raw);
  } catch {
    // Not JSON — hand back the raw string.
  }
  return { event, data };
}

/** A stateful splitter: push decoded text chunks, get back whole events as they complete. */
export function createSseParser() {
  let buffer = "";
  return {
    push(chunk: string): SseEvent[] {
      buffer += chunk;
      const events: SseEvent[] = [];
      let sep: number;
      // Frames are separated by a blank line. We assume LF ("\n\n"), which matches our
      // gateway's output; a CRLF server ("\r\n\r\n") would need that handled too.
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const event = parseSseFrame(frame);
        if (event) events.push(event);
      }
      return events;
    },
  };
}
