"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { SignIn } from "./SignIn";

export function Shell({ children }: { children: ReactNode }) {
  const { token, role, ready, signOut } = useAuth();
  return (
    <>
      <header className="top">
        <Link className="brand" href="/">ClaimLens</Link>
        {token && (
          <nav aria-label="Main">
            <Link href="/">Claims</Link>
            {role !== "reviewer" && <Link href="/new/">New claim</Link>}
            {role === "reviewer" && <Link href="/reviewer/">Review queue</Link>}
          </nav>
        )}
        {token && (
          <span className="row small">
            <span className="muted">Signed in as {role}</span>
            <button className="secondary" onClick={signOut}>Sign out</button>
          </span>
        )}
      </header>
      <main>
        {!ready ? <p role="status">Loading…</p> : token ? children : <SignIn />}
      </main>
    </>
  );
}
