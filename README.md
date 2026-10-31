# ClaimLens

**Pre-check US health-insurance claims before they are submitted, and give reviewers an evidence-backed starting point.**

A large share of US medical claims is denied, pended or reduced on first pass, often for reasons that were visible in the paperwork: a missing prior authorization, a diagnosis that does not support the procedure, an out-of-network provider, a missed timely-filing deadline, a malformed NPI or code, an arithmetic error, an inflated line item. Patients and provider billing offices find out weeks later, and appeals are slow. Payer reviewers read the same 40-page bundles by hand.

ClaimLens reads the itemized bill, discharge summary and plan terms, runs the plan rules and clearinghouse-style code edits, flags billing anomalies, estimates the chance of a query, and explains each finding with the document text it came from. **It is decision support only. Nothing in the system approves or denies a claim; a human reviewer always decides.**

```
 upload ─► extract ─► validate (18 rules) ─► anomalies ─► risk score ─► explain ─► human review
            │            pass / fail / UNKNOWN   price, duplicate,    calibrated,     cited policy
            │            (unknown is never        unbundling, days    per-claim       clauses only,
            │             treated as pass)        beyond stay         reasons         refuses if unsure
            └─ documents are untrusted input: sanitised, schema-bound, no tools
```

## Status and honesty

| Area | State |
|---|---|
| Python core, API, worker, rules, RAG, ML | Built; 170+ automated tests pass; `ruff` and `mypy --strict` clean |
| Web UI (Next.js static export) | Built; type-check, unit test and production build pass |
| Azure adapters | Implemented, **tested against fakes only**, never run against live Azure |
| Bicep infrastructure | Compiles and lints clean, **never deployed** |
| Entra sign-in, LLM extractor, Document Intelligence OCR | Implemented, **not exercised live** |
| Data and model | **Everything is synthetic.** Metrics prove the pipeline works; they say nothing about accuracy on real claims |

Read [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) before quoting any number from this repo.

## Quickstart (no cloud account needed)

Requires Python 3.12+ and (for the UI) Node 20+.

```bash
python -m venv .venv && source .venv/bin/activate
make install                 # pip install -e ".[api,azure,pdf,dev]"
make model                   # train + gate + package the risk model on synthetic data (~3 min)
make demo                    # load 25 synthetic claims, process them, print the reviewer queue

make api                     # API on http://localhost:8000 (processes inline, no worker needed)
claimlens token --tenant demo --role reviewer      # prints a dev JWT (roles: patient, provider, reviewer)
# then:  curl -H "Authorization: Bearer <token>" localhost:8000/v1/reviewer/queue

make web-install && cd apps/web && cp .env.example .env.local && npm run dev
# sign in by pasting a token from `claimlens token`
```

Without a trained model the API still runs: rules, anomaly checks and the explanations work, and the risk score is simply absent.

Other targets: `make test`, `make lint`, `make typecheck`, `make eval` (writes `reports/eval_report.md`), `make web-build`, `make bicep`, `make all`.

### Docker

```bash
docker compose -f docker/docker-compose.yml up --build    # api + worker + web sharing one volume
```

(The Dockerfiles were written but not built in the environment this repo was generated in; expect to fix small things.)

## Repository layout

```
src/claimlens/        cloud-agnostic core
  domain/             Pydantic models (claims, policies, rule results, analysis)
  extraction/         sanitiser, layout, rule-based extractor, document classifier
  rules/              18 plan rules, ICD-10/CPT/NPI checks + YAML plans (synthetic PPO, HMO, HDHP)
  rag/                plan-clause retrieval and cited, refusing Q&A
  ml/                 price book, anomaly model, features, LightGBM risk model, release gate
  synthetic/          deterministic data generator (22 procedures, 40 hospitals in 21 metros, 3 bill layouts)
  adapters/           ports (Protocols), local filesystem adapters, Azure adapters
  services.py        role-filtered use cases       process.py   pipeline + worker loop
  evaluation.py      end-to-end evaluation report  cli.py       generate/train/eval/demo/token/worker
apps/api/             FastAPI service (authn/z, rate limits, security headers)
apps/web/             Next.js 15 UI: patient/provider intake, claim view, reviewer queue
infra/                Bicep: monitoring, identity, data, messaging, AI, compute, web, RBAC
.github/workflows/    CI (lint, types, tests, audit, web, bicep, model gate) and OIDC deploy
docs/                 architecture, security, model card, runbook, sample eval report
tests/                unit, integration (API, worker, adversarial, invariants), model, load
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): components, data flow, Azure mapping, design decisions
- [`docs/SECURITY.md`](docs/SECURITY.md): threat model, prompt injection, tenant isolation, privacy
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md): what the model is, how it was trained and gated, what it cannot tell you
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md): deploying to Azure, operating, incident handling
- [`docs/EVAL_REPORT_SAMPLE.md`](docs/EVAL_REPORT_SAMPLE.md): output of `claimlens eval` on 600 fresh synthetic cases

## Before using this for real claims

This is a reference implementation. Real use needs, at minimum: real labelled outcomes and a fairness review; policy wording and rules signed off by your claims and legal teams; a HIPAA privacy and security risk analysis (Business Associate Agreements with every processor, minimum-necessary access, retention, breach procedures) plus a review of state health-privacy laws; penetration testing; and live validation of the Azure deployment. None of that has been done here.

## Licence

MIT, see [`LICENSE`](LICENSE). The sample policies are invented and do not represent any health plan's terms. CPT is a registered trademark of the American Medical Association; the bundled code-edit table is a small illustrative stand-in, not a licensed code set.
