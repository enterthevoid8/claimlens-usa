"""Billing anomaly detection.

Three layers, cheapest and most explainable first:
1. line-level checks against a peer price book (z-score on log price), duplicates, unbundling, days billed
   beyond the stay: each flag carries evidence a reviewer can verify;
2. a claim-level Isolation Forest over aggregate features, reported as a percentile so a reviewer sees
   "more unusual than 97% of past claims", not a raw score.
Flags are *prompts for a human*, not accusations: an unusual bill can be legitimate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

from claimlens.domain.models import AnomalyFlag, Evidence, HospitalBill, ItemCategory
from claimlens.ml.price_book import PriceBook, default_price_book

PRICE_Z_FLAG = 3.0
_DUP_CATEGORIES = {
    ItemCategory.ROOM,
    ItemCategory.ICU,
    ItemCategory.SURGEON,
    ItemCategory.ANESTHESIA,
    ItemCategory.OR,
    ItemCategory.PROCEDURE,
    ItemCategory.PACKAGE,
    ItemCategory.DIAGNOSTIC,
    ItemCategory.DOCTOR_FEE,
}


@dataclass
class LineAnalysis:
    flags: list[AnomalyFlag]
    price_z_mean: float  # mean of positive z-scores over price-checked items (0 if none)
    price_z_max: float
    price_checked_share: float  # share of line items that could be compared with the price book
    n_duplicates: int
    n_unbundling: int
    n_days_over_stay: int


def _norm(desc: str) -> str:
    return " ".join(desc.lower().split())


def analyse_lines(bill: HospitalBill, book: PriceBook | None = None) -> LineAnalysis:
    book = book or default_price_book()
    flags: list[AnomalyFlag] = []
    zs: list[float] = []
    checked = 0
    for item in bill.line_items:
        chk = book.check(item, bill.procedure, bill.city)
        if chk is None:
            continue
        checked += 1
        zs.append(chk.z)
        if chk.z > PRICE_Z_FLAG:
            flags.append(
                AnomalyFlag(
                    code="price_outlier",
                    description=f"'{item.description}' is billed at {chk.ratio:.1f}x the typical price of ${chk.expected:,.0f}.",
                    score=round(chk.z, 2),
                    evidence=[
                        Evidence(
                            document_id=bill.document_id,
                            field="line_item",
                            text=f"{item.description}: ${item.amount:,.0f}",
                        )
                    ],
                )
            )
    # duplicates
    seen = Counter(
        (_norm(i.description), round(i.amount, 2))
        for i in bill.line_items
        if i.category in _DUP_CATEGORIES
    )
    dups = [(k, n) for k, n in seen.items() if n > 1]
    for (desc, amt), n in dups:
        flags.append(
            AnomalyFlag(
                code="duplicate_line",
                description=f"'{desc}' for ${amt:,.0f} appears {n} times.",
                score=float(n),
                evidence=[Evidence(document_id=bill.document_id, field="line_item", text=desc)],
            )
        )
    # unbundling: an all-inclusive package billed together with its components
    has_package = any(i.category == ItemCategory.PACKAGE for i in bill.line_items)
    components = [
        i
        for i in bill.line_items
        if i.category in (ItemCategory.SURGEON, ItemCategory.ANESTHESIA, ItemCategory.OR)
    ]
    n_unb = 0
    if has_package and components:
        n_unb = len(components)
        flags.append(
            AnomalyFlag(
                code="unbundled_package",
                description="A global surgical package is billed together with separately itemized surgeon, anesthesia or operating-room charges (unbundling).",
                score=float(n_unb),
                evidence=[
                    Evidence(
                        document_id=bill.document_id,
                        field="line_item",
                        text=components[0].description,
                    )
                ],
            )
        )
    # days billed beyond the stay
    n_over = 0
    if bill.admission_date and bill.discharge_date and bill.discharge_date >= bill.admission_date:
        stay = max((bill.discharge_date - bill.admission_date).days, 1)
        for i in bill.line_items:
            if (
                i.category in (ItemCategory.ROOM, ItemCategory.ICU, ItemCategory.NURSING)
                and i.quantity > stay + 1
            ):
                n_over += 1
                flags.append(
                    AnomalyFlag(
                        code="days_exceed_stay",
                        description=f"'{i.description}' is billed for {i.quantity:g} days but the stay was {stay} day(s).",
                        score=round(i.quantity - stay, 1),
                        evidence=[
                            Evidence(
                                document_id=bill.document_id, field="line_item", text=i.description
                            )
                        ],
                    )
                )
    pos = [z for z in zs if z > 0]
    return LineAnalysis(
        flags=flags,
        price_z_mean=float(np.mean(pos)) if pos else 0.0,
        price_z_max=float(max(zs)) if zs else 0.0,
        price_checked_share=checked / len(bill.line_items) if bill.line_items else 0.0,
        n_duplicates=len(dups),
        n_unbundling=n_unb,
        n_days_over_stay=n_over,
    )


# --------------------------------------------------------------------- claim-level Isolation Forest

CLAIM_FEATURES = [
    "log_total",
    "cost_per_day_log",
    "n_items",
    "share_room",
    "share_medicine",
    "share_consumable",
    "share_diagnostic",
    "price_z_mean",
]


class ClaimAnomalyModel:
    """Isolation Forest + the training score distribution, so scores are reported as percentiles."""

    def __init__(self, forest: IsolationForest, ref_scores: np.ndarray) -> None:
        self.forest = forest
        self.ref = np.sort(ref_scores)

    @classmethod
    def fit(cls, X: np.ndarray, seed: int = 7) -> ClaimAnomalyModel:
        forest = IsolationForest(n_estimators=200, contamination="auto", random_state=seed).fit(X)
        return cls(forest, -forest.score_samples(X))

    def percentile(self, x: np.ndarray) -> float:
        s = -self.forest.score_samples(x.reshape(1, -1))[0]
        return float(np.searchsorted(self.ref, s) / len(self.ref))
