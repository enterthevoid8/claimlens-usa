"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { AUTH_MODE, ENTRA } from "./config";
import { isExpired, roleFromToken } from "./jwt";
import type { Role } from "./types";

interface AuthState {
  token: string | null;
  role: Role | null;
  ready: boolean;
  signInWithToken: (token: string) => string | null;
  signInWithMicrosoft: () => Promise<void>;
  signOut: () => void;
  getToken: () => Promise<string | null>;
}

const Ctx = createContext<AuthState | null>(null);
const STORAGE_KEY = "claimlens.dev.token";

// Dev tokens live in sessionStorage so a refresh keeps you signed in; Entra tokens stay in MSAL's own cache.
function readStored(): string | null {
  try {
    const t = sessionStorage.getItem(STORAGE_KEY);
    return t && !isExpired(t) ? t : null;
  } catch {
    return null;
  }
}

let msalInstance: import("@azure/msal-browser").PublicClientApplication | null = null;
async function msal() {
  if (msalInstance) return msalInstance;
  const { PublicClientApplication } = await import("@azure/msal-browser");
  msalInstance = new PublicClientApplication({
    auth: { clientId: ENTRA.clientId, authority: `https://login.microsoftonline.com/${ENTRA.tenantId}`, redirectUri: window.location.origin },
    cache: { cacheLocation: "sessionStorage" },
  });
  await msalInstance.initialize();
  return msalInstance;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      if (AUTH_MODE === "dev") {
        setToken(readStored());
      } else {
        const app = await msal();
        const acct = app.getAllAccounts()[0];
        if (acct) {
          const r = await app.acquireTokenSilent({ scopes: [ENTRA.scope], account: acct }).catch(() => null);
          setToken(r?.accessToken ?? null);
        }
      }
      setReady(true);
    })();
  }, []);

  const signInWithToken = useCallback((t: string) => {
    const trimmed = t.trim();
    if (!roleFromToken(trimmed)) return "That does not look like a ClaimLens token (exactly one role is required).";
    if (isExpired(trimmed)) return "That token has expired.";
    sessionStorage.setItem(STORAGE_KEY, trimmed);
    setToken(trimmed);
    return null;
  }, []);

  const signInWithMicrosoft = useCallback(async () => {
    const app = await msal();
    const r = await app.loginPopup({ scopes: [ENTRA.scope] });
    setToken(r.accessToken);
  }, []);

  const signOut = useCallback(() => {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    setToken(null);
    if (AUTH_MODE === "entra") void msal().then((a) => a.logoutPopup().catch(() => undefined));
  }, []);

  const getToken = useCallback(async () => {
    if (AUTH_MODE === "entra") {
      const app = await msal();
      const acct = app.getAllAccounts()[0];
      if (!acct) return null;
      const r = await app.acquireTokenSilent({ scopes: [ENTRA.scope], account: acct }).catch(() => null);
      if (r) setToken(r.accessToken);
      return r?.accessToken ?? null;
    }
    return token && !isExpired(token) ? token : null;
  }, [token]);

  const value = useMemo<AuthState>(
    () => ({ token, role: token ? roleFromToken(token) : null, ready, signInWithToken, signInWithMicrosoft, signOut, getToken }),
    [token, ready, signInWithToken, signInWithMicrosoft, signOut, getToken],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside <AuthProvider>");
  return v;
}
