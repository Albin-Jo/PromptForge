import { describe, expect, it } from "vitest";
import { POLL_INTERVAL_MS, pollWhilePending } from "./polling";

// Build the fake `query` object React Query hands to a refetchInterval callback.
function query<T>(data: T | undefined, status: "pending" | "success" | "error" = "success") {
  return { state: { data, status } };
}

describe("pollWhilePending", () => {
  const isRunning = (d: { running: boolean }) => d.running;
  const poll = pollWhilePending(isRunning);

  it("keeps polling while the latest data is still running", () => {
    expect(poll(query({ running: true }))).toBe(POLL_INTERVAL_MS);
  });

  it("stops at a terminal state", () => {
    expect(poll(query({ running: false }))).toBe(false);
  });

  it("does not poll before the first response (no data yet)", () => {
    expect(poll(query<{ running: boolean }>(undefined, "pending"))).toBe(false);
  });

  it("stops on a fetch error so a failing endpoint can't spin forever", () => {
    expect(poll(query({ running: true }, "error"))).toBe(false);
  });

  it("honours a custom interval", () => {
    expect(pollWhilePending(isRunning, 500)(query({ running: true }))).toBe(500);
  });
});
