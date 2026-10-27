import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  apiGet,
  apiLogin,
  BackendUnreachableError,
  setAccessToken,
  setUnauthorizedHandler,
} from "@/services/api";
import type { CurrentUser, LoginResponse, Permission } from "@/types/enterprise";

const STORAGE_KEY = "atlas.session";

interface StoredSession {
  token: string;
  expiresAt: string;
}

/** "unreachable": a stored session exists but the API could not be reached to verify it. */
type Status = "checking" | "unreachable" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: Status;
  user: CurrentUser | null;
  /** Why the last session ended, shown on the sign-in page. */
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: (notice?: string) => void;
  /** Re-verify a stored session after the API was unreachable. */
  retry: () => void;
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStored(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as StoredSession;
    return new Date(session.expiresAt).getTime() > Date.now() ? session : null;
  } catch {
    return null;
  }
}

function writeStored(session: StoredSession | null): void {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode): the session simply won't survive a reload.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [stored] = useState(readStored);
  const [status, setStatus] = useState<Status>(stored ? "checking" : "anonymous");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(stored?.expiresAt ?? null);
  const [notice, setNotice] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const logout = useCallback(
    (reason?: string) => {
      setAccessToken(null);
      writeStored(null);
      setUser(null);
      setExpiresAt(null);
      setStatus("anonymous");
      setNotice(reason ?? null);
      // Never show one user's cached data to the next.
      queryClient.clear();
    },
    [queryClient],
  );

  // Restore a stored session by re-validating it with the server. An outage is not a
  // reason to sign the user out; only the server rejecting the token is.
  useEffect(() => {
    if (!stored) return;
    let cancelled = false;
    setAccessToken(stored.token);
    apiGet<CurrentUser>("/api/v1/auth/me")
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof BackendUnreachableError) setStatus("unreachable");
        else logout();
      });
    return () => {
      cancelled = true;
    };
  }, [stored, logout, attempt]);

  useEffect(() => {
    setUnauthorizedHandler(() => logout("Your session has ended. Please sign in again."));
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Sign out when the token expires rather than waiting for a failed request.
  useEffect(() => {
    if (!expiresAt) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    const timer = setTimeout(
      () => logout("Your session expired. Please sign in again."),
      Math.max(remaining, 0),
    );
    return () => clearTimeout(timer);
  }, [expiresAt, logout]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await apiLogin<LoginResponse>({ username, password });
    setAccessToken(response.access_token);
    writeStored({ token: response.access_token, expiresAt: response.expires_at });
    setExpiresAt(response.expires_at);
    setUser(response.user);
    setNotice(null);
    setStatus("authenticated");
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      notice,
      login,
      logout,
      retry: () => {
        setStatus("checking");
        setAttempt((n) => n + 1);
      },
      can: (permission) => Boolean(user?.permissions.includes(permission)),
    }),
    [status, user, notice, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
