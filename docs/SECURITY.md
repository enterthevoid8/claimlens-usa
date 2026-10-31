# Security and privacy

ClaimLens handles health information and financial documents. This page records the threat model, what the code does about each threat, and what it does **not** do. It is a design review, not a certification.

## Assets

1. Patient documents (bills, discharge summaries): protected health information (PHI) and identifiers.
2. Claim analyses (risk scores, anomaly flags): commercially sensitive and, if misused, prejudicial to the patient.
3. Reviewer decisions and the audit trail.
4. Model bundles (integrity matters more than confidentiality).

## Trust boundaries

Browser → API (bearer token) → storage, queue, AI services (managed identity). **Uploaded documents are untrusted input**, even when they come from an authenticated provider.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Cross-tenant access | Tenant comes only from the token claim `tenant_id`. Every repository call is keyed by tenant (Cosmos partition `/tenantId`; local path segment). A claim in another tenant returns **404**, not 403, so existence is not leaked. | `services.py`, adapters |
| Privilege escalation | Exactly one role per token (patient, provider, reviewer). Only reviewers can read the queue or decide. Patients and providers receive filtered views with no risk score, anomalies, features or extracted data. | `auth.py`, `services.py` |
| Path traversal / injection via ids and filenames | `safe_id()` allow-list on every id used as a path or key; blob paths are resolved and checked against the root; filenames are stripped to a printable basename; Cosmos queries are parameterised. | `security.py`, `adapters/local.py` |
| Malicious uploads | Content type is taken from magic bytes, not the client header; allow-list of text, PDF, PNG, JPEG, TIFF; size limit enforced on a bounded read and on `Content-Length`; document count limit per claim. | `layout.py`, `main.py` |
| **Prompt injection in documents** | (1) Heuristic sanitiser flags instruction-like text and rule R015 fails the claim for review. (2) The LLM extraction call has **no tools** and a strict JSON schema, so injected text can at worst change extracted values, not take actions. (3) Rules ignore free text. (4) Q&A can cite only retrieved policy clauses and refuses on low relevance. (5) No automated approve/deny exists to be hijacked. | `sanitize.py`, `openai_llm.py`, `rag/answer.py` |
| Fabricated or tampered bills | Arithmetic and date consistency rules; price-book outliers, duplicates, unbundling; unparsed rows produce UNKNOWN. These raise a flag for a human; they cannot prove fraud. | `rules/`, `ml/anomaly.py` |
| Model tampering | Bundles carry a SHA-256 manifest; every file is hash-verified before load. The Isolation Forest is a pickle (joblib), so it is only loaded after verification. Only the CI deployer identity can write the `models` container. | `risk_model.py`, `infra/modules/rbac.bicep` |
| Secrets leakage | No keys in settings; managed identity everywhere; shared-key and local auth disabled on Storage, Cosmos, Service Bus, OpenAI, Search (prod) and Application Insights where supported; deploy uses OIDC, no stored client secret. | `infra/`, `deploy.yml` |
| PII in logs | A logging filter redacts Social Security numbers, e-mail addresses and US phone numbers; application logs carry ids, not document text. Names and addresses are not pattern-detectable, so the code simply never logs document content. | `security.py` |
| Abuse and cost | Per-principal rate limits (120/min general, 20/min explain), body size cap, bounded concurrency in the worker, max job attempts then dead-letter. | `deps.py`, `process.py` |
| Browser attacks | `nosniff`, `no-store`, `no-referrer`; CORS restricted to configured origins and methods; tokens are kept in `sessionStorage` (MSAL cache for Entra), so an XSS bug would expose them; there is no inline script and the app is a static export. | `main.py`, `apps/web` |
| Misconfiguration in production | `environment=prod` refuses to start with dev auth, the local backend or inline processing. | `settings.py` |

## Known gaps

- The injection sanitiser is a heuristic. On the project's own test set it flags 100% of known phrasings but only about **20% of novel phrasings** (`docs/EVAL_REPORT_SAMPLE.md`). The structural controls above are what actually protect you; do not rely on the flag.
- Rate limiting is **per process, in memory**. With several API replicas the effective limit is multiplied; put API Management or a shared counter in front for production.
- Azure adapters and Bicep were never run against a real subscription. Role-assignment scopes, private networking and Search free-tier RBAC support are unverified. No private endpoints or VNet integration are configured.
- No malware scanning of uploads. Add Defender for Storage or an equivalent before accepting files from the public.
- The audit log is create-only by convention and role design; it is not cryptographically chained or immutable storage.
- No WAF, no DDoS plan, no penetration test, no SBOM signing.
- Cosmos and Blob use Microsoft-managed encryption keys, not customer-managed keys.

## Privacy and HIPAA (United States)

This is engineering guidance, not legal advice; get counsel to review. A health plan or provider using this system is a HIPAA covered entity, and the cloud vendors that process PHI on its behalf are business associates.

- **Consent.** Creating a claim requires `consent_given=true`; creation without it is rejected. HIPAA generally permits use of PHI for payment and health care operations without patient authorization, so this flag is an application-level control (useful for state laws and patient trust), not the legal basis.
- **Minimum necessary and purpose limitation.** Roles see only what they need (see below). Documents are used to produce the analysis; they are not used to train models in this design. The synthetic training data contains no real records.
- **Deletion.** (HIPAA gives no general right to erasure, but deletion on request is useful where state law or contract requires it.) `DELETE /v1/claims/{id}` removes the documents and claim record and writes a `claim.deleted` audit event containing ids only. Blob soft-delete (7 days in the Bicep defaults) and Key Vault retention mean data can persist briefly after deletion; document this in your privacy notice.
- **Retention and audit.** No automatic retention job is implemented. Define a period (HIPAA requires certain compliance documentation to be kept six years; medical-record retention is set by state law and contract) and add a scheduled purge before production. The audit log records who accessed which claim and when, which supports HIPAA audit-control expectations, but it is not tamper-proof (see gaps).
- **Business associate agreements and regions.** The example deploy command uses a US region (`eastus2`). Before any PHI is processed, confirm that every Azure service in the data flow (Storage, Cosmos DB, Service Bus, Document Intelligence, Azure OpenAI, AI Search, Container Apps, Application Insights) is covered by your BAA with Microsoft, and that Azure OpenAI abuse-monitoring/data-retention settings meet your policy. Model and region availability varies.
- **Minimisation for roles.** Providers and patients never see model output about the claim; reviewers see only their tenant.
- **State laws.** Several states add health-data rules beyond HIPAA (for example the Washington My Health My Data Act and California's CPRA/CMIA). Have counsel map them to your deployment.
- **Automated decisions.** None are made; every outcome is a recorded human decision with a reviewer id and note.

## Reporting a vulnerability

Open a private security advisory on the repository (or contact the maintainers directly). Do not file public issues containing exploit details or real patient data.
