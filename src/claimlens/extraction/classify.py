"""Document type classification. Keyword scoring offline; Azure custom classifier is an adapter."""

from __future__ import annotations

from claimlens.domain.models import DocumentType

_SIGNALS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.HOSPITAL_BILL: (
        "itemized hospital bill",
        "itemized statement",
        "ub-04",
        "statement of charges",
        "account no",
        "invoice no",
        "total charges",
        "amount",
        "rate",
        "qty",
    ),
    DocumentType.DISCHARGE_SUMMARY: (
        "discharge summary",
        "condition at discharge",
        "attending physician",
        "diagnosis",
        "admission type",
        "advice on discharge",
    ),
    DocumentType.PREAUTH_APPROVAL: (
        "prior authorization",
        "prior auth",
        "preauthorization",
        "pre-authorization",
        "authorization number",
        "authorization approval",
        "utilization management",
    ),
    DocumentType.ID_PROOF: (
        "member id card",
        "insurance card",
        "driver license",
        "driver's license",
        "passport",
        "state id",
        "identity proof",
    ),
    DocumentType.CLAIM_FORM: (
        "claim form",
        "cms-1500",
        "subscriber signature",
        "assignment of benefits",
    ),
    DocumentType.PRESCRIPTION: ("prescription", "rx", "dosage"),
    DocumentType.LAB_REPORT: (
        "lab report",
        "reference range",
        "specimen",
        "hemoglobin",
    ),
}

# Header phrases are worth more than incidental words.
_STRONG = {
    "itemized hospital bill",
    "itemized statement",
    "ub-04",
    "discharge summary",
    "prior authorization",
    "pre-authorization",
    "claim form",
    "cms-1500",
    "lab report",
}


def classify_document(text: str, filename: str = "") -> DocumentType:
    haystack = (filename + "\n" + text[:4000]).lower()
    best, best_score = DocumentType.OTHER, 0
    for doc_type, needles in _SIGNALS.items():
        score = sum(3 if n in _STRONG else 1 for n in needles if n in haystack)
        if score > best_score:
            best, best_score = doc_type, score
    return best if best_score >= 3 else DocumentType.OTHER
