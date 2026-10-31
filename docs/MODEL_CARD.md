# Model card: ClaimLens query-risk model

## Read this first

**The model has only ever seen synthetic data.** The numbers below describe how well it recovers a *simulated* process that this repository's authors wrote. They demonstrate that the training, calibration, gating and serving pipeline works end to end. They are **not** evidence of accuracy on real US health-insurance claims, and must not be quoted as such.

## What it does

Estimates the probability that a claim will be **denied, pended or reduced** on first pass by a payer reviewer, given the plan, the extracted bill and discharge summary, rule outcomes and billing anomalies. Output: a calibrated probability, a band (low < 25%, medium, high ≥ 60%) and up to three plain-language reasons from per-claim TreeSHAP contributions.

## Intended use

- Ordering a reviewer's queue so likely-problem claims are read first.
- Telling a reviewer *why* a claim looks risky, with the underlying rule results and anomaly evidence one click away.

## Not intended for

- Approving, denying, or reducing any claim. There is no such path in the product.
- Judging fraud, making medical-necessity determinations or judging a patient's credibility.
- Use on any population, health plan or document format the model was not validated on. That includes every real one today.

## Model

- LightGBM gradient-boosted trees, binary objective, with **monotone-increasing** constraints on 13 features where the direction is not in doubt (failed blocker and warning rules, unverifiable checks, missing documents, duplicate lines, unbundling, days beyond stay, price outliers, provider history, suspicious document text, timely-filing and length-of-stay ratios).
- Isotonic calibration fitted on a held-out calibration split; stored as JSON and applied with linear interpolation.
- Features (32): rule outcome counts, missing documents, price z-scores, anomaly counts, claim-level Isolation Forest percentile, provider historical denial rate, cost-sharing terms (coinsurance, network requirement), in-network status, length of stay relative to the typical stay for the procedure, days from discharge to filing relative to the plan's timely-filing limit, emergency admission, plan age, waiting-period proximity, extraction confidence, injection-flag count, and size/cost-per-day terms. The list is in `ml/features.py`.
- Provider denial rate uses **leave-one-out** on training rows so a row's own label never leaks into its feature. It is computed from the training split only.
- Splits: 60% train, 10% validation (early stopping), 15% calibration, 15% test. Default dataset: 5,000 synthetic cases, seed 42.

## Training data

`claimlens.synthetic` generates cases from 22 procedures (CPT and MS-DRG), 40 fictional hospitals with valid-checksum NPIs across 21 US metros in three market tiers, three plan types (PPO, HMO, HDHP) and three bill layouts. Labels are Bernoulli draws from rule outcomes plus soft latent factors (price inflation, duplicates, unbundling, days beyond stay, provider propensity, a payer records-request hold on very large claims) plus noise. Because the generator wrote the labels, the **ceiling** AUC (using the true generating probability) is about 0.88 (0.877 on the last run); the model cannot honestly beat that, and in this setting reaching it just means it recovered the simulator.

## Results (synthetic)

Release-gate run on the held-out test split (`make model`):

| Check | Result | Threshold |
|---|---|---|
| ROC AUC | 0.827 | ≥ 0.75 |
| Brier score | 0.151 | ≤ 0.20 |
| Calibration error (ECE) | 0.055 | ≤ 0.06 |
| Gain over rules-only baseline | +0.024 AUC | ≥ +0.02 |
| Subgroup AUC (plan type × 3, market tier × 3) | 0.807 – 0.837 | ≥ 0.68 and within 0.08 of overall |

Fresh-seed evaluation on 600 new synthetic cases (`make eval`, see `docs/EVAL_REPORT_SAMPLE.md`): model AUC 0.849 vs 0.816 for rules alone; ECE 0.025 vs 0.195; precision in the top 20% 0.74 vs 0.72. The small margin over the rules baseline is expected because the simulator derives most of its signal from the same rules. Two gate checks pass narrowly on the held-out split (ECE 0.055 against 0.06; gain +0.024 against +0.02), so a retrain with a different seed can fail the gate; that is the gate doing its job.

The gate blocks promotion if any check fails, and the CI `model-gate` job runs it on every change.

## Limitations

- **Synthetic labels.** The real query/reduction process depends on payer policy and edits, clearinghouse and utilization-management vendors, state mandates, temporal drift, and reviewer inconsistency, none of which are modelled.
- **Parity checks are coarse.** Subgroups are plan type and market tier only. They do not cover age, sex, race, ethnicity, language, disability, income or any other protected characteristic, and the synthetic data does not contain those. A real deployment needs a proper fairness review with real data before the model influences anyone's queue position.
- **Feedback loops.** If reviewers trust the score and read low-risk claims less carefully, labels collected later will be biased by the score itself. Track reviewer overrides and sample low-risk claims for audit.
- **Price book and code edits.** The reference prices and the diagnosis-to-procedure table are synthetic and illustrative; they are not a licensed CPT/ICD-10 code set or any payer's coverage policy. Real use needs a price book from your own paid-claims history.
- **Extraction dependence.** Features inherit extraction errors. Extraction confidence is a feature, but the rule-based parser scores near 100% only because it shares vocabulary with the generator. Real scans go through OCR and an LLM extractor that has not been evaluated here.
- **Explanations are about the model, not causes.** "Provider history raises the estimated chance" describes a statistical association, not a claim about the provider's conduct.

## Monitoring and retraining (when real data exists)

Log score, band and reviewer outcome for every decision. Track calibration and AUC by month and by subgroup; alert on drift in input features and on rising reviewer overrides. Retrain on reviewed outcomes only, re-run the gate, and keep the previous bundle for rollback (`models/risk/CURRENT` points at the promoted version; bundles are immutable and hash-verified).

## Versioning

Bundle id `risk-<model-file-hash>-<training-data-id>` is stored in every `RiskScore.model_version` and every audit event, so any decision can be traced to the exact model that was shown.
