"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { makeApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const MAX_BYTES = 10 * 1024 * 1024;

export default function NewClaim() {
  const { getToken, role } = useAuth();
  const router = useRouter();
  const api = useMemo(() => makeApi(getToken), [getToken]);
  const [policyId, setPolicyId] = useState("");
  const [consent, setConsent] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (role === "reviewer") return <p>Reviewers cannot submit claims.</p>;

  const tooBig = files.find((f) => f.size > MAX_BYTES);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const claim = await api.createClaim(policyId.trim(), consent);
      for (const f of files) await api.upload(claim.claim_id, f);
      await api.submit(claim.claim_id);
      router.push(`/claim/?id=${encodeURIComponent(claim.claim_id)}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>New claim</h1>
      <form className="card" onSubmit={onSubmit}>
        <label htmlFor="policy">Policy number</label>
        <input id="policy" type="text" value={policyId} onChange={(e) => setPolicyId(e.target.value)} required maxLength={64} />
        <label htmlFor="files">Documents (itemized hospital bill, discharge summary, prior authorization letter)</label>
        <input id="files" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.txt" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        {tooBig && <p className="error" role="alert">{tooBig.name} is larger than 10 MB.</p>}
        <label style={{ fontWeight: 400, display: "flex", gap: 8, marginTop: 16 }}>
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>I agree to ClaimLens processing these documents, including health information, to pre-check my claim. I can withdraw this and have the documents deleted at any time.</span>
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <p><button type="submit" disabled={busy || !consent || !policyId.trim() || files.length === 0 || !!tooBig}>{busy ? "Uploading…" : "Submit for pre-check"}</button></p>
      </form>
      <p className="disclaimer small">This is a pre-check. It highlights missing documents and possible issues; it does not approve or deny a claim.</p>
    </>
  );
}
