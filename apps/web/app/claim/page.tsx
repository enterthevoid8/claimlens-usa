"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Checks } from "@/components/Checks";
import { humanStatus, makeApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Answer, Claim } from "@/lib/types";

function ClaimView() {
  const id = useSearchParams().get("id") ?? "";
  const { getToken, role } = useAuth();
  const router = useRouter();
  const api = useMemo(() => makeApi(getToken), [getToken]);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(() => api.getClaim(id).then(setClaim).catch((e: Error) => setError(e.message)), [api, id]);
  useEffect(() => { if (id) void load(); }, [id, load]);
  useEffect(() => {
    if (!claim || !["received", "processing"].includes(claim.status)) return;
    const t = setInterval(() => void load(), 2000);
    return () => clearInterval(t);
  }, [claim, load]);

  if (!id) return <p>No claim selected.</p>;
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!claim) return <p role="status">Loading…</p>;

  const a = claim.analysis;
  const waiting = ["received", "processing"].includes(claim.status);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    setAsking(true);
    try { setAnswer(await api.explain(id, question)); } catch (err) { setError((err as Error).message); } finally { setAsking(false); }
  }
  async function decide(decision: string) {
    try { setClaim(await api.decide(id, decision, note)); } catch (err) { setError((err as Error).message); }
  }
  async function remove() {
    if (!window.confirm("Delete this claim and its documents? This cannot be undone.")) return;
    await api.remove(id).catch((err: Error) => setError(err.message));
    router.push("/");
  }

  return (
    <>
      <h1>Claim {claim.claim_id}</h1>
      <p className="muted">Policy {claim.policy_id} · <span role="status">{humanStatus[claim.status] ?? claim.status}</span></p>
      {waiting && <p className="banner" role="status" aria-live="polite">We are reading your documents. This usually takes under a minute.</p>}
      {claim.status === "failed" && <p className="banner error">We could not process this claim automatically. A person will look at it.</p>}

      {a && (
        <>
          <p className="disclaimer">{a.summary}</p>
          {a.missing_documents.length > 0 && (
            <div className="card"><strong>Please add:</strong> {a.missing_documents.map((d) => d.replaceAll("_", " ")).join(", ")}</div>
          )}
          <h2>Checks</h2>
          <Checks rules={a.rules} />
        </>
      )}

      {role === "reviewer" && a && (
        <>
          <h2>Reviewer panel</h2>
          {a.risk ? (
            <div className="card">
              <p><span className={`pill ${a.risk.band}`}>{a.risk.band} risk</span> {" "}
                Estimated chance of a query or reduction: <strong>{Math.round(a.risk.probability * 100)}%</strong>
                <span className="muted small"> (model {a.risk.model_version}, calibrated on synthetic data)</span></p>
              <ul>{a.risk.reasons.map((r) => <li key={r.feature}>{r.text}</li>)}</ul>
            </div>
          ) : <p className="muted">No risk model is loaded, so no score is shown.</p>}
          {a.anomalies && a.anomalies.length > 0 && (
            <div className="card"><strong>Billing flags</strong><ul>{a.anomalies.map((f, i) => <li key={i}>{f.description}</li>)}</ul></div>
          )}
          {a.extracted && a.extracted.injection_flags.length > 0 && (
            <div className="card"><strong className="error">Suspicious text in the documents</strong>
              <ul>{a.extracted.injection_flags.map((f, i) => <li key={i}><code>{f}</code></li>)}</ul></div>
          )}
          {a.extracted?.bill && (
            <details className="card"><summary>Extracted bill ({a.extracted.bill.line_items.length} lines, read with {Math.round(a.extracted.extraction_confidence * 100)}% of fields)</summary>
              <table><thead><tr><th>Item</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
                {a.extracted.bill.line_items.map((i, k) => <tr key={k}><td>{i.description}</td><td>{i.quantity}</td><td>{i.amount.toLocaleString("en-US", { style: "currency", currency: "USD" })}</td></tr>)}
              </tbody></table></details>
          )}
          {["ready", "needs_info"].includes(claim.status) && (
            <div className="card">
              <label htmlFor="note">Decision note (required to deny)</label>
              <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
              <p className="row">
                <button onClick={() => void decide("approve")}>Approve</button>
                <button className="secondary" onClick={() => void decide("request_info")}>Request information</button>
                <button className="danger" disabled={!note.trim()} onClick={() => void decide("deny")}>Deny</button>
              </p>
            </div>
          )}
        </>
      )}

      {claim.decision && (
        <div className="card"><strong>Decision: {claim.decision.decision.replace("_", " ")}</strong>{claim.decision.note && <p>{claim.decision.note}</p>}</div>
      )}

      {a && (
        <>
          <h2>Ask about your policy</h2>
          <form onSubmit={ask} className="card">
            <label htmlFor="q">Question</label>
            <input id="q" type="text" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} placeholder="e.g. What is the room rent limit?" />
            <p><button type="submit" disabled={asking || !question.trim()}>{asking ? "Looking…" : "Ask"}</button></p>
            {answer && (
              <div aria-live="polite">
                <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer}</p>
                {answer.citations.length > 0 && <p className="muted small">Sources: {answer.citations.map((c) => `Clause ${c.clause} (${c.title})`).join("; ")}</p>}
              </div>
            )}
          </form>
        </>
      )}

      <p><button className="danger" onClick={() => void remove()}>Withdraw consent and delete this claim</button></p>
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p role="status">Loading…</p>}><ClaimView /></Suspense>;
}
