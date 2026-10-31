# Architecture

## Goals and non-goals

**Goals.** Catch avoidable claim problems early; give reviewers cited evidence instead of a black-box score; keep patient documents private; run the same code on a laptop and on Azure.

**Non-goals.** ClaimLens does not approve or deny claims, does not replace the health plan's adjudication, and does not make medical-necessity determinations (the diagnosis-to-procedure check only flags a likely mismatch for a human). There is no field in the data model that can hold an automated decision.

## Flow

```
Browser (Next.js static site)
   │  Entra ID token (RS256) / dev token locally
   ▼
API (FastAPI, Container App)  ──►  Blob (documents)        ──┐
   │  create → upload → submit        Cosmos DB (claims, policies, audit; partition /tenantId)
   │                                  Service Bus (claim-jobs, duplicate detection, DLQ)
   ▼                                                          │
Worker (Container App, KEDA scaled on queue depth) ◄──────────┘
   1. fetch documents          4. anomalies (price book, duplicates, unbundling, stay)
   2. extract (layout → LLM    5. risk score (LightGBM + calibration + TreeSHAP reasons)
      or rule parser)          6. persist ClaimAnalysis, set status READY, audit event
   3. validate (18 rules)
```

`submit` is an explicit step so a provider billing office can upload several documents and correct mistakes before analysis starts. Reviewers read the queue ordered by modelled risk and record `approve`, `deny` or `request_info` themselves.

## Ports and adapters

`claimlens.adapters.ports` defines Protocols: `BlobStore`, `ClaimRepository`, `JobQueue`, `AuditLog`, `LayoutAnalyzer`, `StructuredExtractor`, `PolicyIndex`, `TextGenerator`. The core imports only these.

| Port | Local (laptop, CI) | Azure |
|---|---|---|
| BlobStore | directory, atomic writes | Blob Storage (`claims` and `models` containers) |
| ClaimRepository | JSON files | Cosmos DB, parameterised queries, partition `/tenantId` |
| JobQueue | `pending/ → inflight/ → dead/` with atomic rename | Service Bus (duplicate detection, dead-letter queue) |
| AuditLog | JSONL | Cosmos (create-only container) |
| LayoutAnalyzer | text and text-layer PDF | Document Intelligence `prebuilt-layout` (OCR) |
| StructuredExtractor | rule-based parser | Azure OpenAI structured output, strict schema, no tools |
| PolicyIndex | in-memory hybrid (coverage + cosine over hashed vectors) | AI Search hybrid with semantic ranker |
| TextGenerator | template answer | Azure OpenAI chat (answer only from retrieved clauses) |

Azure SDKs are imported lazily, so the local install does not need them and tests do not need credentials. Azure authentication is always `DefaultAzureCredential` with managed identity; no connection strings or keys appear in settings.

## Components

### Extraction (`extraction/`)
Layout analysis → document classification (itemized bill, discharge summary, prior authorization) → structured extraction into `HospitalBill`, `DischargeSummary`. Every extracted value carries `Evidence` (document id plus the source text). Rows that look like bill lines but cannot be parsed go to `unparsed_rows`; they are never dropped silently and they make rule R008 return UNKNOWN. A sanitiser flags instruction-like text before the content reaches any model.

### Rules (`rules/`)
Eighteen deterministic rules (coverage period, eligibility waiting period, timely filing, diagnosis-supports-procedure, exclusions, length of stay, accident and third-party liability, bill arithmetic, date consistency, required documents, prior authorization, in/out-of-network status, benefit limits, name match, embedded instructions, extraction confidence, unreadable files, NPI and ICD-10/CPT code formats). Pre-existing conditions are deliberately **not** a rule: the ACA bars US plans from excluding them, and eligibility waiting periods are capped at 90 days. Each returns `pass`, `fail` or `unknown` with evidence and a policy clause number. A rule that raises an exception becomes `unknown`. Plans are YAML (`rules/policies/`: `ppo_gold`, `hmo_silver`, `hdhp_bronze`), validated by Pydantic at load. Network rules differ by plan type: HMO and EPO pay nothing for non-emergency out-of-network care (blocker), PPO and HDHP pay less and the member may be balance billed (warning), and emergency care is protected under the No Surprises Act. Diagnosis-to-procedure and typical-stay logic comes from a small illustrative code-edit table in `rules/coding.py`.

### Anomalies (`ml/anomaly.py`)
Line-level: z-score of log price against a peer price book by procedure and metro market; exact duplicates; package billed with its components (unbundling); room, ICU or nursing days beyond the length of stay. Claim-level: Isolation Forest, reported as a percentile of past claims. Flags are prompts for a human, not accusations.

### Risk model (`ml/`)
LightGBM with monotone constraints on features where direction is not in doubt (more failed blockers must not lower risk), isotonic calibration stored as JSON, and per-claim reasons from native TreeSHAP (`pred_contrib`). Features are computed by the same function (`analysis.analyse_claim`) in training and serving. Bundles are packaged with a SHA-256 manifest and verified before load; a release gate blocks promotion unless discrimination, calibration, improvement over the rules-only baseline and subgroup parity all pass.

### Policy Q&A (`rag/`)
Plan wording is chunked by clause. Retrieval scores clause coverage and cosine similarity. The answer step may cite only retrieved clauses; if relevance is below a threshold it returns a refusal instead of guessing. Citations are validated against the retrieved set.

### Services (`services.py`)
All use cases take a `Principal` (subject, tenant, role) and return role-filtered views. Patients and providers see rule results and missing documents. Only reviewers see risk, anomalies, features and extracted data.

## Design decisions

- **Unknown is not pass.** A missing or unreadable input yields UNKNOWN, which routes the claim to review. It is never silently treated as compliant.
- **No automated outcome.** The suggested route is `review` or `request_info`; there is no approve/deny path.
- **Rules before ML.** The model sees rule outcomes as features and must beat a rules-only baseline to ship. Rules remain the explanation of record.
- **Local-first.** Everything runs without a cloud account, so tests and demos are cheap and deterministic.
- **Separate containers for data and models.** The API and worker can read `models` but not write it; only the CI deployer principal can.
- **Static web app.** The UI is a static export that talks to the API with a bearer token; there is no server-side session to protect.

## Azure resources (Bicep, `infra/`)

Log Analytics and Application Insights; user-assigned managed identities for API and worker; Storage (blob), Cosmos DB (serverless in dev, provisioned in prod), Service Bus, Document Intelligence, Azure OpenAI (chat and embedding deployments), AI Search, Container Registry, Container Apps environment with API and KEDA-scaled worker, Static Web App, Key Vault, and scoped role assignments (container-level where possible). Shared-key and local auth are disabled where the service allows.
