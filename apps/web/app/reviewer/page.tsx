"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { makeApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { QueueItem } from "@/lib/types";

export default function Queue() {
  const { getToken, role } = useAuth();
  const api = useMemo(() => makeApi(getToken), [getToken]);
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (role === "reviewer") api.queue().then(setItems).catch((e: Error) => setError(e.message));
  }, [api, role]);

  if (role !== "reviewer") return <p>Reviewer access required.</p>;
  return (
    <>
      <h1>Review queue</h1>
      <p className="muted">Highest modelled risk first. The score only decides the order you look at claims in, never the outcome.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {items === null && !error && <p role="status">Loading…</p>}
      {items?.length === 0 && <p className="muted">Nothing waiting.</p>}
      {items && items.length > 0 && (
        <table>
          <thead><tr><th>Claim</th><th>Risk</th><th>Why</th><th>Flags</th><th>Route</th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.claim_id}>
                <td><Link href={`/claim/?id=${encodeURIComponent(i.claim_id)}`}>{i.claim_id}</Link></td>
                <td>{i.risk_probability === null ? "not scored" : <><span className={`pill ${i.risk_band}`}>{i.risk_band}</span> {Math.round(i.risk_probability * 100)}%</>}</td>
                <td className="small">{i.top_reason ?? "—"}</td>
                <td>{i.n_flags}</td>
                <td>{i.route === "request_info" ? "needs documents" : "review"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
