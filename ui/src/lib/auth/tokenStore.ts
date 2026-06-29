// Token storage per ADR 0019:
//   - access token  -> in memory only (module variable), lost on reload
//   - refresh token -> localStorage, so a reload can silently restore the session
//
// Deliberately a plain module, not React state: the access token must be readable by
// the fetch wrapper outside the render cycle, and keeping it out of state avoids
// re-renders on every refresh.

const REFRESH_KEY = "promptforge.refreshToken";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem(REFRESH_KEY);
  } else {
    localStorage.setItem(REFRESH_KEY, token);
  }
}

/** Persist a freshly-issued access + refresh pair (login). */
export function setTokens(access: string, refresh: string): void {
  setAccessToken(access);
  setRefreshToken(refresh);
}

/** Drop all tokens (logout, or an unrecoverable 401). */
export function clearTokens(): void {
  setAccessToken(null);
  setRefreshToken(null);
}
