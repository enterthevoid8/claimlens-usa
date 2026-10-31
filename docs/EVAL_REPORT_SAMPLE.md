# ClaimLens evaluation report

Generated 2026-10-27T17:24:24.657661+00:00 on 600 **synthetic** cases (seed 1234). These numbers verify the pipeline; they do not measure real-world accuracy.

## Extraction (rule-based extractor)
The parser and the generator share a vocabulary of field labels and layouts, so near-perfect scores here are expected and say little about unseen real documents. Real scans go through Document Intelligence and the LLM extractor, which must be evaluated on hand-labelled real samples.

### Bill fields (exact match)
| metric | value |
|---|---|
| bill_number | 1.0 |
| hospital_name | 1.0 |
| patient_name | 1.0 |
| admission_date | 1.0 |
| discharge_date | 1.0 |
| diagnosis | 1.0 |
| procedure | 1.0 |
| total_claimed | 1.0 |
| city | 1.0 |
| state | 1.0 |
| provider_npi | 1.0 |
| procedure_code | 1.0 |
| diagnosis_codes | 1.0 |

### Line items
| metric | value |
|---|---|
| precision | 0.9992 |
| recall | 0.9876 |
| f1 | 0.9934 |

### Discharge summary fields
| metric | value |
|---|---|
| diagnosis | 1.0 |
| admission_date | 1.0 |
| discharge_date | 1.0 |
| diagnosis_codes | 1.0 |
| is_emergency | 1.0 |
| is_accident | 1.0 |
| third_party_liability | 1.0 |

## Rule outcomes: extracted vs. true data
| metric | value |
|---|---|
| agreement | 0.9927 |
| false_pass_rate | 0.0 |
| became_unknown_rate | 0.0073 |
| note | false_pass = rule fails on the true data but passes on the extracted data (the dangerous direction). |

## Anomaly detection (planted anomalies)
| anomaly | planted | recall | false-positive rate |
|---|---|---|---|
| inflate | 94 | 0.979 | 0.002 |
| duplicate | 24 | 0.958 | 0.0 |
| unbundle | 12 | 0.917 | 0.0 |
| days_over | 7 | 1.0 | 0.0 |

## Risk model (fresh seed)
Model `risk-87b7c6d3-eb62e255`

| metric | model | rules only |
|---|---|---|
| n | 600.0 | 600.0 |
| positive_rate | 0.29 | 0.29 |
| roc_auc | 0.8494 | 0.8155 |
| pr_auc | 0.6764 | 0.5956 |
| brier | 0.1291 | 0.1931 |
| ece | 0.0245 | 0.1954 |
| precision_at_20pct | 0.7417 | 0.7167 |

Ceiling AUC using the true generating probability: 0.8766

## Policy Q&A
| metric | value |
|---|---|
| in_scope_questions | 54 |
| hit_at_1 | 0.944 |
| hit_at_3 | 1.0 |
| wrongly_refused_in_scope | 0.111 |
| out_of_scope_questions | 10 |
| out_of_scope_refused | 1.0 |
| note | Questions were written by the same author as the retriever and the wording is generated from the same policy object, so treat these as optimistic. |

## Adversarial documents
| payload set | runs | flagged | failed check disappeared | extracted total changed |
|---|---|---|---|---|
| known phrasing | 60 | 1.0 | 0 | 0 |
| novel phrasing | 60 | 0.2 | 0 | 0 |

Detection is a heuristic tuned on the first list and will miss novel phrasing (second list). The safety property is structural: extraction has no tools, rules ignore free text, and nothing automated approves or denies a claim.
