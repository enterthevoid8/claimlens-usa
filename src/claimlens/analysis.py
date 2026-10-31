"""The analysis core: documents + policy in, ``ClaimAnalysis`` out. Pure and I/O-free.

Both the worker (serving) and the trainer (building features from synthetic documents) call this one
function, so what the model is trained on is exactly what it sees in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from claimlens import __version__
from claimlens.adapters.ports import StructuredExtractor
from claimlens.domain.models import (
    AnomalyFlag,
    ClaimAnalysis,
    DocumentRef,
    Policy,
    RuleResult,
    RuleStatus,
    Severity,
)
from claimlens.extraction.extract import DocText, extract_claim_data
from claimlens.ml.anomaly import ClaimAnomalyModel, analyse_lines
from claimlens.ml.features import build_features
from claimlens.ml.hospital_stats import HospitalStats
from claimlens.ml.price_book import PriceBook
from claimlens.ml.risk_model import RiskModel
from claimlens.rules.base import RuleContext, RuleEngine
from claimlens.rules.builtin import default_rules, missing_documents

CLAIM_UNUSUAL_PERCENTILE = 0.985


@dataclass
class Models:
    risk: RiskModel | None = None
    anomaly: ClaimAnomalyModel | None = None
    hospital_stats: HospitalStats | None = None
    price_book: PriceBook | None = None


def summarise(rules: list[RuleResult], missing: list[str]) -> str:
    passed = sum(r.status == RuleStatus.PASS for r in rules)
    failed = [r for r in rules if r.status == RuleStatus.FAIL]
    unknown = sum(r.status == RuleStatus.UNKNOWN for r in rules)
    parts = [f"{passed} of {len(rules)} checks passed."]
    if failed:
        parts.append(
            f"{len(failed)} need attention: "
            + "; ".join(r.title.lower() for r in failed[:4])
            + ("..." if len(failed) > 4 else "")
            + "."
        )
    if unknown:
        parts.append(f"{unknown} could not be verified from the documents.")
    if missing:
        parts.append("Missing documents: " + ", ".join(m.replace("_", " ") for m in missing) + ".")
    parts.append("This is a pre-check only. A claims reviewer makes every decision.")
    return " ".join(parts)


def analyse_claim(
    *,
    claim_id: str,
    policy: Policy,
    docs: list[DocText],
    refs: list[DocumentRef],
    extractor: StructuredExtractor,
    models: Models | None = None,
    today: date | None = None,
    hospital_loo_label: int | None = None,
    unreadable: list[str] | None = None,
) -> ClaimAnalysis:
    models = models or Models()
    data = extract_claim_data(docs, extractor)
    data.unreadable_documents = list(unreadable or [])
    ctx = RuleContext(
        policy=policy, data=data, documents=refs, **({"today": today} if today else {})
    )
    rules = RuleEngine(default_rules()).run(ctx)
    missing = missing_documents(ctx)
    lines = (
        analyse_lines(data.bill, models.price_book) if data.bill and data.bill.line_items else None
    )
    features = build_features(
        ctx,
        rules,
        lines,
        hospital_stats=models.hospital_stats,
        anomaly_model=models.anomaly,
        hospital_loo_label=hospital_loo_label,
    )
    anomalies: list[AnomalyFlag] = list(lines.flags) if lines else []
    pct = features.get("claim_anomaly_pct")
    if pct is not None and pct >= CLAIM_UNUSUAL_PERCENTILE:
        anomalies.append(
            AnomalyFlag(
                code="unusual_bill",
                description=f"This bill is more unusual than {pct:.0%} of past claims. That can be legitimate; a reviewer should look.",
                score=round(pct, 3),
            )
        )
    risk = models.risk.score(features) if models.risk is not None else None
    blockers_unknown = any(
        r.status == RuleStatus.UNKNOWN and r.severity == Severity.BLOCKER for r in rules
    )
    route = "request_info" if missing or blockers_unknown else "review"
    return ClaimAnalysis(
        claim_id=claim_id,
        extracted=data,
        rules=rules,
        anomalies=anomalies,
        risk=risk,
        missing_documents=missing,
        features=features,
        summary=summarise(rules, [m.value for m in missing]),
        suggested_route=route,
        pipeline_version=__version__,
    )
