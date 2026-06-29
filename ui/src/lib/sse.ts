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
  // Lines may be terminated by LF, CR, or CRLF (SSE spec); split on any of them so a
  // CRLF stream doesn't leave a trailing "\r" on each field for trim() to mop up.
  for (const line of frame.split(/\r\n|\r|\n/)) {
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
      // Frames are separated by a blank line. Our gateway emits LF ("\n\n"); a CRLF proxy
      // emits "\r\n\r\n", which contains no "\n\n" substring — so we look for both and take
      // whichever boundary comes first. We do NOT handle bare-CR ("\r\r") or mixed boundaries
      // ("\n\r\n"); the SSE spec permits them, but no source we talk to produces them.
      for (;;) {
        const lf = buffer.indexOf("\n\n");
        const crlf = buffer.indexOf("\r\n\r\n");
        let sep: number;
        let len: number;
        if (crlf !== -1 && (lf === -1 || crlf < lf)) {
          sep = crlf;
          len = 4;
        } else if (lf !== -1) {
          sep = lf;
          len = 2;
        } else {
          break;
        }
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + len);
        const event = parseSseFrame(frame);
        if (event) events.push(event);
      }
      return events;
    },
  };
}
