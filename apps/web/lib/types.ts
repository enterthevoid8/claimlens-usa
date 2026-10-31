export type Role = "patient" | "provider" | "reviewer";
export type ClaimStatus = "received" | "processing" | "ready" | "needs_info" | "failed" | "decided";
export type RuleStatus = "pass" | "fail" | "unknown";

export interface RuleResult {
  rule_id: string;
  title: string;
  status: RuleStatus;
  severity: "info" | "warn" | "blocker";
  message: string;
  clause: string | null;
  evidence: { text: string; field?: string | null }[];
}

export interface RiskReason {
  feature: string;
  contribution: number;
  direction: "increases" | "decreases";
  text: string;
}

export interface RiskScore {
  probability: number;
  band: "low" | "medium" | "high";
  reasons: RiskReason[];
  model_version: string;
}

export interface AnomalyFlag {
  code: string;
  description: string;
  score: number;
  evidence: { text: string }[];
}

export interface Analysis {
  summary: string;
  suggested_route: "review" | "request_info";
  rules: RuleResult[];
  missing_documents: string[];
  // reviewer-only
  risk?: RiskScore | null;
  anomalies?: AnomalyFlag[];
  extracted?: {
    extractor: string;
    extraction_confidence: number;
    injection_flags: string[];
    bill: { hospital_name?: string; patient_name?: string; total_claimed?: number; diagnosis?: string; procedure?: string; line_items: { description: string; quantity: number; amount: number }[] } | null;
  };
}

export interface Claim {
  claim_id: string;
  policy_id: string;
  status: ClaimStatus;
  created_at: string;
  documents: { document_id: string; filename: string; doc_type: string | null; size_bytes: number }[];
  analysis: Analysis | null;
  decision: { decision: string; note: string; reviewer_id: string; decided_at: string } | null;
  error: string | null;
}

export interface QueueItem {
  claim_id: string;
  status: ClaimStatus;
  created_at: string;
  risk_probability: number | null;
  risk_band: string | null;
  top_reason: string | null;
  n_flags: number;
  route: string | null;
}

export interface Answer {
  answer: string;
  refused: boolean;
  citations: { clause: string; title: string; quote: string }[];
}
