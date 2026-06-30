import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, setAuthFailureHandler } from "./api";
import { toast } from "./toast";
import { clearTokens, getRefreshToken, setTokens } from "./auth/tokenStore";

// Minimal Response stand-in matching what api.ts touches (ok/status/statusText/text()).
function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  } as Response;
}

// A 429 Response stand-in that also exposes a `Retry-After` header (the only path that reads
// headers), so we can assert the retry hint is surfaced.
function rateLimitedResponse(retryAfter: number) {
  return {
    ok: false,
    status: 429,
    statusText: "",
    headers: { get: (name: string) => (name === "Retry-After" ? String(retryAfter) : null) },
    text: async () => JSON.stringify({ detail: "rate limit exceeded" }),
  } as unknown as Response;
}

function authHeader(init: RequestInit | undefined): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.["Authorization"];
}

describe("apiFetch token refresh", () => {
  beforeEach(() => {
    clearTokens();
    localStorage.clear();
    setAuthFailureHandler(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("refreshes once on a 401, then retries the original request and succeeds", async () => {
    setTokens("expired-access", "refresh-1");
    let refreshCalls = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        if (u.endsWith("/auth/refresh")) {
          refreshCalls += 1;
          return jsonResponse(200, { access_token: "fresh-access" });
        }
        // The original endpoint: 401 with the stale token, 200 once refreshed.
        return authHeader(init) === "Bearer fresh-access"
          ? jsonResponse(200, { value: 42 })
          : jsonResponse(401, { detail: "token expired" });
      }),
    );

    const result = await apiFetch<{ value: number }>("/widgets");
    expect(result).toEqual({ value: 42 });
    expect(refreshCalls).toBe(1);
  });

  it("single-flights: two concurrent 401s trigger only one refresh", async () => {
    setTokens("expired-access", "refresh-1");
    let refreshCalls = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        if (u.endsWith("/auth/refresh")) {
          refreshCalls += 1;
          return jsonResponse(200, { access_token: "fresh-access" });
        }
        return authHeader(init) === "Bearer fresh-access"
          ? jsonResponse(200, { ok: true })
          : jsonResponse(401, { detail: "token expired" });
      }),
    );

    const [a, b] = await Promise.all([apiFetch("/a"), apiFetch("/b")]);
    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
  });

  it("clears tokens and notifies on an unrecoverable refresh failure", async () => {
    setTokens("expired-access", "refresh-1");
    const onFailure = vi.fn();
    setAuthFailureHandler(onFailure);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const u = String(url);
        if (u.endsWith("/auth/refresh")) return jsonResponse(401, { detail: "refresh expired" });
        return jsonResponse(401, { detail: "token expired" });
      }),
    );

    await expect(apiFetch("/widgets")).rejects.toMatchObject({ status: 401 });
    expect(getRefreshToken()).toBeNull();
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 429's Retry-After and fires one rate-limit toast", async () => {
    const errorToast = vi.spyOn(toast, "error").mockReturnValue("toast-id");
    vi.stubGlobal("fetch", vi.fn(async () => rateLimitedResponse(30)));

    await expect(apiFetch("/widgets")).rejects.toMatchObject({
      status: 429,
      retryAfterSeconds: 30,
    });

    expect(errorToast).toHaveBeenCalledTimes(1);
    expect(errorToast).toHaveBeenCalledWith(
      expect.stringContaining("30s"),
      expect.objectContaining({ id: "rate-limit" }),
    );
  });

  it("does not attempt a refresh when there is no refresh token", async () => {
    // No tokens set at all.
    let refreshCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/refresh")) refreshCalls += 1;
        return jsonResponse(401, { detail: "unauthorized" });
      }),
    );

    await expect(apiFetch("/widgets")).rejects.toMatchObject({ status: 401 });
    expect(refreshCalls).toBe(0);
  });
});
