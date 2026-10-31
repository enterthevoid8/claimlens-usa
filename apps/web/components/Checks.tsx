import type { RuleResult } from "@/lib/types";

const LABEL = { pass: "Looks fine", fail: "Needs attention", unknown: "Could not verify" } as const;

export function Checks({ rules }: { rules: RuleResult[] }) {
  const order = { fail: 0, unknown: 1, pass: 2 } as const;
  const sorted = [...rules].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <ul className="checks">
      {sorted.map((r) => (
        <li key={r.rule_id}>
          <span><span className={`pill ${r.status}`}>{LABEL[r.status]}</span></span>
          <span>
            <strong>{r.title}</strong>
            <br />
            {r.message}
            {r.clause && <span className="muted small"> (policy clause {r.clause})</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
