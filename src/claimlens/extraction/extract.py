"""Combine per-document text into one ``ExtractedClaimData`` object."""

from __future__ import annotations

from dataclasses import dataclass

from claimlens.adapters.ports import StructuredExtractor
from claimlens.domain.models import (
    DischargeSummary,
    DocumentType,
    ExtractedClaimData,
    HospitalBill,
)
from claimlens.extraction.sanitize import clean_text


@dataclass
class DocText:
    document_id: str
    doc_type: DocumentType
    text: str


def _confidence(bill: HospitalBill | None, discharge: DischargeSummary | None) -> float:
    expected = 0
    found = 0
    if bill is not None:
        for present in (
            bill.bill_number,
            bill.hospital_name,
            bill.patient_name,
            bill.admission_date,
            bill.discharge_date,
            bill.diagnosis,
            bill.total_claimed,
            bill.line_items,
            not bill.unparsed_rows,
            bill.procedure_code,
            bill.diagnosis_codes,
            bill.provider_npi,
        ):
            expected += 1
            found += 1 if present else 0
    if discharge is not None:
        for present in (
            discharge.patient_name,
            discharge.diagnosis,
            discharge.admission_date,
            discharge.discharge_date,
            discharge.diagnosis_codes,
        ):
            expected += 1
            found += 1 if present else 0
    return round(found / expected, 3) if expected else 0.0


def extract_claim_data(docs: list[DocText], extractor: StructuredExtractor) -> ExtractedClaimData:
    flags: list[str] = []
    bill: HospitalBill | None = None
    discharge: DischargeSummary | None = None
    has_preauth = False
    for doc in docs:
        text, doc_flags = clean_text(doc.text)
        flags.extend(f"[{doc.document_id}] {f}" for f in doc_flags)
        if doc.doc_type == DocumentType.HOSPITAL_BILL and bill is None:
            bill = extractor.extract_bill(text)
            bill.document_id = doc.document_id
        elif doc.doc_type == DocumentType.DISCHARGE_SUMMARY and discharge is None:
            discharge = extractor.extract_discharge(text)
            discharge.document_id = doc.document_id
        elif doc.doc_type == DocumentType.PREAUTH_APPROVAL:
            has_preauth = True
    return ExtractedClaimData(
        bill=bill,
        discharge=discharge,
        has_preauth_approval=has_preauth,
        injection_flags=flags,
        extraction_confidence=_confidence(bill, discharge),
        extractor=extractor.name,
    )
