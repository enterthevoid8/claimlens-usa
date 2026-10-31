"use client";

import { useState } from "react";
import { AUTH_MODE } from "@/lib/config";
import { useAuth } from "@/lib/auth";

export function SignIn() {
  const { signInWithToken, signInWithMicrosoft } = useAuth();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <section>
      <h1>Check your claim before the health plan does</h1>
      <p className="muted">ClaimLens reads your hospital bills and records, checks them against your plan and flags what is missing or likely to be questioned. A claims reviewer makes every decision.</p>
      {AUTH_MODE === "entra" ? (
        <button onClick={() => signInWithMicrosoft().catch(() => setError("Sign-in did not complete."))}>Sign in with Microsoft</button>
      ) : (
        <form className="card" onSubmit={(e) => { e.preventDefault(); setError(signInWithToken(value)); }}>
          <p className="small muted">Development mode. Create a token with <code>claimlens token --role provider --tenant demo</code> and paste it here.</p>
          <label htmlFor="token">Access token</label>
          <input id="token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
          {error && <p className="error" role="alert">{error}</p>}
          <p><button type="submit" disabled={!value.trim()}>Sign in</button></p>
        </form>
      )}
      {AUTH_MODE === "entra" && error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
