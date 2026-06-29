import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiFetch, setAuthFailureHandler } from "../api";
import { roleSatisfies, type Role } from "./permissions";
import { clearTokens, getRefreshToken, setTokens } from "./tokenStore";
import type { TokenPair, User } from "./types";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  /** True until the initial session-restore attempt finishes (avoids flicker-then-bounce). */
  isRestoring: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isRestoring, setIsRestoring] = useState(true);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  // Let the fetch layer drop us to logged-out when a refresh ultimately fails.
  useEffect(() => {
    setAuthFailureHandler(() => setUser(null));
    return () => setAuthFailureHandler(null);
  }, []);

  // Proactive session restore on load (ADR 0019): if a refresh token survived the reload,
  // confirm the session via /auth/me before rendering protected pages. The 401-refresh flow
  // in apiFetch mints a fresh access token transparently.
  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (!getRefreshToken()) {
        setIsRestoring(false);
        return;
      }
      try {
        const me = await apiFetch<User>("/auth/me");
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) {
          clearTokens();
          setUser(null);
        }
      } finally {
        if (!cancelled) setIsRestoring(false);
      }
    }
    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiFetch<TokenPair>("/auth/login", {
      method: "POST",
      body: { email, password },
      skipAuth: true,
    });
    setTokens(tokens.access_token, tokens.refresh_token);
    const me = await apiFetch<User>("/auth/me");
    setUser(me);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: user !== null, isRestoring, login, logout }),
    [user, isRestoring, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

/**
 * Whether the current user meets a role bar (hierarchical: admin satisfies editor).
 * Drives "disable the action + tooltip" so non-permitted users never fire a doomed request.
 * Logged-out / still-restoring → no user → denied.
 */
export function useCan(required: Role): boolean {
  const { user } = useAuth();
  return roleSatisfies(user?.role, required);
}
