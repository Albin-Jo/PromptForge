// Fetch wrapper over the PromptForge API (ADR 0019).
//
// Responsibilities:
//   - base URL + JSON encode/decode + typed errors
//   - attach the in-memory access token as a Bearer header
//   - on a 401, transparently refresh the access token *once* and retry
//   - single-flight the refresh so N concurrent 401s trigger one refresh, not N
//   - on unrecoverable auth failure, clear tokens and notify the app (-> redirect)

import { clearTokens, getAccessToken, getRefreshToken, setAccessToken } from "./auth/tokenStore";
import { rateLimitMessage, toast } from "./toast";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

/** The API origin, exported for non-JSON callers (e.g. the streaming playground). */
export const API_BASE_URL = BASE_URL;

/** An HTTP error carrying the status and any parsed error body from the API. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  /** Seconds to wait before retrying, parsed from a 429's `Retry-After` header (else undefined). */
  readonly retryAfterSeconds?: number;

  constructor(status: number, message: string, body: unknown, retryAfterSeconds?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  /** Skip the Bearer header + 401-refresh dance (used by the auth endpoints themselves). */
  skipAuth?: boolean;
}

// The app registers a callback so the fetch layer can tell React "you're logged out"
// without importing React. Set by AuthContext on mount.
let onAuthFailure: (() => void) | null = null;
export function setAuthFailureHandler(handler: (() => void) | null): void {
  onAuthFailure = handler;
}

/** One in-flight refresh shared by all callers (single-flight). */
let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise;

  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new ApiError(401, "no refresh token", null);
  }

  refreshPromise = (async () => {
    try {
      const { access_token } = await rawRequest<{ access_token: string }>("/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshToken },
        skipAuth: true,
      });
      setAccessToken(access_token);
      return access_token;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/** A single HTTP round-trip: build the request, send it, parse the JSON body. No auth retry. */
async function rawRequest<T>(path: string, options: RequestOptions): Promise<T> {
  const { method = "GET", body, signal, skipAuth } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (!skipAuth) {
    const token = getAccessToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    signal,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  const parsed: unknown = text.length > 0 ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : response.statusText;

    if (response.status === 429) {
      // The rate-limit middleware sends a Retry-After hint (seconds); surface it as a single,
      // friendly toast on every page. A fixed toast id collapses a burst of concurrent 429s
      // into one toast rather than stacking N of them.
      const header = Number(response.headers.get("Retry-After"));
      const retryAfterSeconds = Number.isFinite(header) && header > 0 ? header : undefined;
      toast.error(rateLimitMessage(retryAfterSeconds), { id: "rate-limit" });
      throw new ApiError(response.status, detail, parsed, retryAfterSeconds);
    }

    throw new ApiError(response.status, detail, parsed);
  }

  return parsed as T;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, options);
  } catch (err) {
    // Only a 401 on an authed request is recoverable, and only if we have a refresh token.
    const recoverable =
      err instanceof ApiError && err.status === 401 && !options.skipAuth && getRefreshToken() !== null;
    if (!recoverable) {
      throw err;
    }

    try {
      await refreshAccessToken();
    } catch {
      // Refresh failed -> the session is truly dead. Clear and let the app redirect to /login.
      clearTokens();
      onAuthFailure?.();
      throw err;
    }

    // One retry with the fresh access token.
    return rawRequest<T>(path, options);
  }
}
