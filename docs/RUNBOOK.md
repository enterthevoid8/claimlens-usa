# Runbook

> **Status.** The Bicep templates compile and lint clean, and the deploy workflow is written, but **neither has been run against a real Azure subscription.** Treat the first deployment to a dev subscription as part of the work: expect to fix role-assignment ordering, quota, region and SKU availability issues. Do not deploy to production before a dev run succeeds end to end.

## 1. One-time setup

### 1.1 Microsoft Entra ID

1. **API app registration** (`claimlens-api`)
   - Application ID URI: `api://<api-client-id>` (this is `ENTRA_AUDIENCE`).
   - Expose a scope `access_as_user`.
   - Define **app roles** with values exactly `patient`, `provider`, `reviewer` (allowed member types: Users). Assign users or groups to roles in *Enterprise applications → Users and groups*.
   - Tokens must be **v2.0**: set `requestedAccessTokenVersion: 2` in the manifest.
2. **Tenant claim.** The API reads the claim `tenant_id` to scope all data. Entra does not emit a claim of that name by default (`tid` is the directory tenant, not your health plan or provider group). Decide what a "tenant" is for you and emit it as `tenant_id`, for example with a [claims-mapping policy](https://learn.microsoft.com/entra/identity-platform/saml-claims-customization) or an optional claim sourced from a directory extension attribute. **A token without it is rejected (401), which is the safe failure.** If a single organisation is enough, map a constant.
3. **Web app registration** (`claimlens-web`): SPA platform, redirect URIs for `http://localhost:3000` and your Static Web App URL; grant it the `access_as_user` permission. Its client ID is `WEB_CLIENT_ID`.

### 1.2 GitHub → Azure (OIDC, no secrets)

Create a deployment app registration (or managed identity) and add a **federated credential** for each GitHub environment (`dev`, `prod`; require reviewers on `prod`). Give it, on the resource group: *Contributor* and *Role Based Access Control Administrator* (the templates create role assignments), plus *Storage Blob Data Contributor* on the `models` container is granted by the templates through `deployerPrincipalId`.

Repository **variables** (not secrets): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_DEPLOYER_OBJECT_ID` (object ID of the deployer principal), `ENTRA_AUDIENCE`, `WEB_CLIENT_ID`, `ENTRA_API_SCOPE` (`api://<api-client-id>/access_as_user`).

### 1.3 First deployment

```bash
az group create -n rg-claimlens-dev -l eastus2
# edit infra/parameters/dev.bicepparam: set entraAudience; optionally webOrigin and openAiLocation
az deployment group create -g rg-claimlens-dev -f infra/main.bicep -p infra/parameters/dev.bicepparam \
   -p deployerPrincipalId=<object-id>
```

Notes:
- The first deployment uses a placeholder container image; the **Deploy** workflow builds the real images in ACR and updates the apps.
- Azure OpenAI model/region availability and quota vary. If the chat or embedding model deployments fail, set `deployModels=false` and create deployments in the portal named `chat` and `embedding` (the names the apps are configured with), or change `CLAIMLENS_OPENAI_DEPLOYMENT` / `CLAIMLENS_OPENAI_EMBEDDING_DEPLOYMENT` on both apps.
- `docIntelSku` defaults to free `F0` in dev (low page limits).
- Set `useLlmExtraction` / `useLlmExplanations` to `true` only after you have evaluated them on real, hand-labelled documents (see `MODEL_CARD.md`).

### 1.4 Create the search index and load policies

Run these once per environment from a machine where you are signed in with `az login` and hold *Search Service Contributor* (index creation) and *Search Index Data Contributor* (indexing) on the Search service, and *Cosmos DB Built-in Data Contributor* on the account. Export the same `CLAIMLENS_*` endpoints the apps use (visible in the Container App's environment variables).

```bash
export CLAIMLENS_BACKEND=azure CLAIMLENS_SEARCH_ENDPOINT=https://<search>.search.windows.net \
       CLAIMLENS_COSMOS_ENDPOINT=... CLAIMLENS_STORAGE_ACCOUNT_URL=... CLAIMLENS_OPENAI_ENDPOINT=... \
       CLAIMLENS_OPENAI_EMBEDDING_DEPLOYMENT=...
claimlens init-search
claimlens register-policy --tenant <tenant_id> --policy-id POL-123 --product ppo_gold \
    --holder "Maria Garcia" --start-date 2026-01-01 --network-provider "Lakeview Medical Center"
```

`register-policy` stores the policy and indexes its clauses. The three bundled plans (`ppo_gold`, `hmo_silver`, `hdhp_bronze`) are **synthetic**. Replace `src/claimlens/rules/policies/*.yaml` with your real plan terms (deductible, coinsurance, out-of-pocket maximum, timely-filing limit, prior-authorization list, exclusions), reviewed by your claims and compliance teams, and have the rules (`rules/builtin.py`) reviewed against your actual wording.

### 1.5 Bootstrap a model

The Deploy workflow trains the synthetic demo model and publishes it (`claimlens train` → `claimlens upload-model`), then points both apps at it with `CLAIMLENS_MODEL_BLOB_PREFIX`. That model is for demonstration. Production needs a model trained and gated on **real labelled outcomes**.

## 2. Day-to-day

| Task | How |
|---|---|
| Health | `GET /healthz` (process up), `GET /readyz` (process ready, reports the loaded risk-model version, or `null` if none; it does **not** probe Azure dependencies) |
| Logs / traces | Application Insights (OpenTelemetry); Log Analytics for Container Apps console logs |
| Scale | API: Container Apps HTTP rules. Worker: KEDA on Service Bus queue depth |
| Rollback app | `az containerapp revision list/activate`, or re-run Deploy on a previous commit |
| Rollback model | Set `CLAIMLENS_MODEL_BLOB_PREFIX` to the previous bundle prefix on both apps; bundles are immutable |
| Add a tenant | Emit the new `tenant_id` for its users; register its policies (§1.4) |
| Erase a claim | `DELETE /v1/claims/{id}` (owner or reviewer); see `SECURITY.md` for residual soft-delete windows |

## 3. Alerts to create (not provisioned by the templates)

- Service Bus **dead-letter count > 0**
- Queue age (oldest active message) > 10 minutes
- API 5xx rate and p95 latency
- Worker restarts / failed jobs
- Spike in 401/403 (credential stuffing or misconfigured tokens)
- Azure OpenAI throttling (429) and spend

## 4. Dead-letter queue

Messages are dead-lettered after `max_job_attempts` (default 3) failed deliveries. The claim is marked `failed` with a short, non-sensitive error.

1. Peek the DLQ (portal or `az servicebus`), note the `claim_id` and the reason.
2. Fix the cause (bad policy id, unreadable file, downstream outage).
3. Have the owner re-submit the claim (`POST /v1/claims/{id}/submit` after correcting documents) or re-send the message.
4. Never edit claim records by hand; every change should leave an audit event.

## 5. Incident response

**Suspected data exposure** (misrouted tenant, leaked token, public storage):
1. Contain: revoke sessions (Entra), rotate/disable the affected app registration or role assignment, set the API Container App to 0 replicas if needed.
2. Preserve: export Application Insights, Log Analytics and the `audit` container before changing anything.
3. Scope: use audit events (actor, tenant, resource, time) to list which claims were read by whom. Cross-tenant reads should be impossible by construction; any evidence of one is a defect to treat as a security incident.
4. Notify: involve your privacy officer and counsel immediately. Under the HIPAA Breach Notification Rule, a covered entity must notify affected individuals without unreasonable delay and no later than 60 days after discovery, notify HHS (immediately for breaches of 500 or more people, annually otherwise) and, for large breaches, the media; business associates must notify the covered entity. State breach laws may impose shorter deadlines. Confirm current requirements with counsel.
5. Recover and review: fix, add a regression test (see `tests/integration/test_api.py` isolation tests), and record the post-incident review.

**Suspected prompt injection or tampered documents:** the claim should already be routed to review (R015). Check the flagged evidence, confirm that no extracted total or rule result changed (the adversarial tests assert this invariant), and add the new phrasing to `extraction/sanitize.py` plus a test. Remember the sanitiser is only a tripwire.

**Model misbehaviour** (scores look wrong, calibration drift, a subgroup is mis-scored): roll back the model (§2), keep the rule-based flow running (it is independent of the model), and open a review of the training data and gate thresholds before re-promoting.

## 6. Before production

- A signed **BAA** with Microsoft covering every service that touches PHI, and a HIPAA security risk analysis.
- A successful dev deployment, then a pen test and threat-model review.
- Private endpoints / VNet integration, WAF or API Management in front of the API, customer-managed keys if required.
- Upload malware scanning; shared rate limiting.
- Defined retention and a scheduled purge.
- Real policy wording, rules reviewed by claims/compliance, real price book, real labelled data, fairness review, reviewer training on how to use (and how not to over-trust) the score.
