"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { humanStatus, makeApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Claim } from "@/lib/types";

export default function Home() {
  const { getToken, role } = useAuth();
  const api = useMemo(() => makeApi(getToken), [getToken]);
  const [claims, setClaims] = useState<Claim[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listClaims().then(setClaims).catch((e: Error) => setError(e.message));
  }, [api]);

  return (
    <>
      <h1>{role === "reviewer" ? "All claims" : "Your claims"}</h1>
      {role !== "reviewer" && <p><Link className="btn" href="/new/">Start a new claim</Link></p>}
      {error && <p className="error" role="alert">{error}</p>}
      {claims === null && !error && <p role="status">Loading…</p>}
      {claims?.length === 0 && <p className="muted">No claims yet.</p>}
      {claims && claims.length > 0 && (
        <table>
          <thead><tr><th>Claim</th><th>Policy</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.claim_id}>
                <td><Link href={`/claim/?id=${encodeURIComponent(c.claim_id)}`}>{c.claim_id}</Link></td>
                <td>{c.policy_id}</td>
                <td>{humanStatus[c.status] ?? c.status}</td>
                <td>{new Date(c.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
