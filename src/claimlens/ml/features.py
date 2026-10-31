"""Feature construction: one function used for training *and* serving, so there is no train/serve skew.

Deliberately excluded: patient age, sex, race, name, ZIP code/city and any other attribute that is either protected or
a likely proxy. Subgroup checks in the model gate look at plan product and market tier (metro size).
"""

from __future__ import annotations

import math

from claimlens.domain.models import ItemCategory, RuleResult, RuleStatus, Severity
from claimlens.ml.anomaly import CLAIM_FEATURES, ClaimAnomalyModel, LineAnalysis
from claimlens.ml.hospital_stats import HospitalStats
from claimlens.rules.base import RuleContext
from claimlens.rules.coding import lookup

FEATURE_NAMES: list[str] = [
    "log_total",
    "los_days",
    "cost_per_day_log",
    "n_items",
    "share_room",
    "share_medicine",
    "share_consumable",
    "share_diagnostic",
    "share_procedure_fees",
    "policy_age_days_log",
    "within_waiting",
    "coinsurance_pct",
    "plan_requires_network",
    "n_fail_blocker",
    "n_fail_warn",
    "n_unknown",
    "missing_docs",
    "los_ratio",
    "filing_lag_ratio",
    "in_network",
    "extraction_confidence",
    "n_injection_flags",
    "price_z_mean",
    "price_z_max",
    "price_checked_share",
    "n_duplicates",
    "n_unbundling",
    "n_days_over_stay",
    "claim_anomaly_pct",
    "hospital_hist_rate",
    "hospital_hist_log_n",
    "is_emergency",
]

# Features whose effect on risk must never decrease as the value grows (enforced in training).
MONOTONE_UP = {
    "n_fail_blocker",
    "n_fail_warn",
    "n_unknown",
    "missing_docs",
    "los_ratio",
    "filing_lag_ratio",
    "price_z_mean",
    "price_z_max",
    "n_duplicates",
    "n_unbundling",
    "n_days_over_stay",
    "n_injection_flags",
    "hospital_hist_rate",
}

Features = dict[str, float | None]


def build_features(
    ctx: RuleContext,
    rules: list[RuleResult],
    lines: LineAnalysis | None,
    *,
    hospital_stats: HospitalStats | None = None,
    anomaly_model: ClaimAnomalyModel | None = None,
    hospital_loo_label: int | None = None,
) -> Features:
    f: Features = dict.fromkeys(FEATURE_NAMES)
    bill, d, p = ctx.data.bill, ctx.data.discharge, ctx.policy
    f["coinsurance_pct"] = p.coinsurance_pct
    f["plan_requires_network"] = float(p.plan_type.requires_network)
    f["extraction_confidence"] = ctx.data.extraction_confidence
    f["n_injection_flags"] = float(len(ctx.data.injection_flags))
    f["n_fail_blocker"] = float(
        sum(r.status == RuleStatus.FAIL and r.severity == Severity.BLOCKER for r in rules)
    )
    f["n_fail_warn"] = float(
        sum(r.status == RuleStatus.FAIL and r.severity == Severity.WARN for r in rules)
    )
    f["n_unknown"] = float(sum(r.status == RuleStatus.UNKNOWN for r in rules))
    f["missing_docs"] = float(len([t for t in p.required_documents if t not in ctx.present_types]))
    adm, dis = ctx.admission_date, ctx.discharge_date
    if adm:
        age = (adm - p.start_date).days
        f["policy_age_days_log"] = math.log1p(max(age, 0))
        f["within_waiting"] = float(age < p.waiting_period_days)
    los = max((dis - adm).days, 0) if adm and dis else None
    f["los_days"] = float(los) if los is not None else None
    service_end = dis or adm
    if service_end:
        f["filing_lag_ratio"] = max((ctx.today - service_end).days, 0) / max(
            p.timely_filing_days, 1
        )
    edit = lookup(bill.procedure_code if bill else None)
    if edit is not None and los is not None:
        f["los_ratio"] = los / max(edit.typical_los[1], 1)
    if d is not None:
        f["is_emergency"] = None if d.is_emergency is None else float(d.is_emergency)
    if bill is not None and bill.total_claimed:
        total = bill.total_claimed
        f["log_total"] = math.log(total)
        f["cost_per_day_log"] = math.log(total / max(los or 1, 1))
        f["n_items"] = float(len(bill.line_items))
        if bill.line_items:

            def share(*cats: ItemCategory) -> float:
                return sum(i.amount for i in bill.line_items if i.category in cats) / total

            f["share_room"] = share(ItemCategory.ROOM, ItemCategory.ICU)
            f["share_medicine"] = share(ItemCategory.MEDICINE)
            f["share_consumable"] = share(ItemCategory.CONSUMABLE)
            f["share_diagnostic"] = share(ItemCategory.DIAGNOSTIC)
            f["share_procedure_fees"] = share(
                ItemCategory.SURGEON,
                ItemCategory.ANESTHESIA,
                ItemCategory.OR,
                ItemCategory.PROCEDURE,
                ItemCategory.PACKAGE,
            )
        if p.network_providers and bill.hospital_name:
            r = next((r for r in rules if r.rule_id == "R012"), None)
            if r is not None and r.status != RuleStatus.UNKNOWN:
                f["in_network"] = float(r.status == RuleStatus.PASS)
    if lines is not None:
        f["price_z_mean"] = lines.price_z_mean
        f["price_z_max"] = lines.price_z_max
        f["price_checked_share"] = lines.price_checked_share
        f["n_duplicates"] = float(lines.n_duplicates)
        f["n_unbundling"] = float(lines.n_unbundling)
        f["n_days_over_stay"] = float(lines.n_days_over_stay)
    if anomaly_model is not None and all(
        f[k] is not None for k in CLAIM_FEATURES if k != "claim_anomaly_pct"
    ):
        import numpy as np

        x = np.array([f[k] for k in CLAIM_FEATURES], dtype=float)
        f["claim_anomaly_pct"] = anomaly_model.percentile(x)
    if hospital_stats is not None and bill is not None and bill.hospital_name:
        rate, logn = hospital_stats.lookup(bill.hospital_name, exclude_label=hospital_loo_label)
        f["hospital_hist_rate"], f["hospital_hist_log_n"] = rate, logn
    return f
