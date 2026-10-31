"""Domain models.

Everything here is plain Pydantic: no Azure types, no I/O. Extraction output is deliberately
permissive (optional fields, no cross-field validators) so that bad or missing data surfaces as a
rule result of ``unknown``/``fail`` instead of an exception that hides the problem.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


# --------------------------------------------------------------------------- enums


class DocumentType(StrEnum):
    HOSPITAL_BILL = "hospital_bill"
    DISCHARGE_SUMMARY = "discharge_summary"
    PREAUTH_APPROVAL = "preauth_approval"
    ID_PROOF = "id_proof"
    CLAIM_FORM = "claim_form"
    PRESCRIPTION = "prescription"
    LAB_REPORT = "lab_report"
    OTHER = "other"


class ItemCategory(StrEnum):
    ROOM = "room"
    ICU = "icu"
    NURSING = "nursing"
    DOCTOR_FEE = "doctor_fee"
    SURGEON = "surgeon"
    ANESTHESIA = "anesthesia"
    OR = "operating_room"
    PROCEDURE = "procedure"
    MEDICINE = "medicine"
    CONSUMABLE = "consumable"
    DIAGNOSTIC = "diagnostic"
    PACKAGE = "package"
    ADMIN = "admin"
    OTHER = "other"


class ClaimStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    READY = "ready"  # analysed, waiting for a human
    NEEDS_INFO = "needs_info"  # analysed, documents or answers missing
    FAILED = "failed"
    DECIDED = "decided"


class RuleStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"  # not enough information: never treated as a pass


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    BLOCKER = "blocker"


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionType(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    REQUEST_INFO = "request_info"


class Role(StrEnum):
    PATIENT = "patient"
    PROVIDER = "provider"
    REVIEWER = "reviewer"


# --------------------------------------------------------------------------- evidence & extraction


class Evidence(BaseModel):
    """Pointer back to the source text for a fact or a rule outcome."""

    document_id: str | None = None
    page: int | None = None
    field: str | None = None
    text: str = ""


class LineItem(BaseModel):
    description: str
    category: ItemCategory = ItemCategory.OTHER
    quantity: float = 1.0
    unit_price: float | None = None
    amount: float
    code: str | None = None
    service_date: date | None = None
    page: int | None = None


class HospitalBill(BaseModel):
    """Itemised facility bill (UB-04 style summary)."""

    bill_number: str | None = None
    hospital_name: str | None = None
    provider_npi: str | None = None  # 10-digit National Provider Identifier
    city: str | None = None
    state: str | None = None  # two-letter USPS code
    patient_name: str | None = None
    admission_date: date | None = None
    discharge_date: date | None = None
    diagnosis: str | None = None
    procedure: str | None = None
    diagnosis_codes: list[str] = Field(default_factory=list)  # ICD-10-CM, principal first
    procedure_code: str | None = None  # principal CPT/HCPCS code, or "DRG ###" for medical stays
    room_type: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    total_claimed: float | None = None
    unparsed_rows: list[str] = Field(
        default_factory=list
    )  # table rows that looked like items but could not be read
    document_id: str | None = None


class DischargeSummary(BaseModel):
    patient_name: str | None = None
    diagnosis: str | None = None
    procedure: str | None = None
    admission_date: date | None = None
    discharge_date: date | None = None
    diagnosis_codes: list[str] = Field(default_factory=list)
    is_emergency: bool | None = None
    is_accident: bool | None = None
    third_party_liability: bool | None = None  # another party's insurance may be primary
    treating_doctor: str | None = None
    document_id: str | None = None


class ExtractedClaimData(BaseModel):
    bill: HospitalBill | None = None
    discharge: DischargeSummary | None = None
    has_preauth_approval: bool = False
    injection_flags: list[str] = Field(default_factory=list)
    unreadable_documents: list[str] = Field(default_factory=list)  # "filename: reason"
    extraction_confidence: float = 1.0  # 0..1, share of expected fields found
    extractor: str = "unknown"


# --------------------------------------------------------------------------- policy


class Exclusion(BaseModel):
    code: str
    title: str
    keywords: list[str]
    clause: str


class BenefitLimit(BaseModel):
    procedure: str
    keywords: list[str]
    max_amount: float
    clause: str = "6.1"


class PlanType(StrEnum):
    PPO = "PPO"
    HMO = "HMO"
    EPO = "EPO"
    HDHP = "HDHP"  # high-deductible health plan (PPO network rules)

    @property
    def requires_network(self) -> bool:
        """HMO and EPO plans pay nothing out of network except for emergencies."""
        return self in (PlanType.HMO, PlanType.EPO)


class Policy(BaseModel):
    """A member's health plan as it applies to one claim (cost-sharing accumulators as of the claim)."""

    policy_id: str
    tenant_id: str
    insurer: str = "Example Health Plan"
    product_name: str
    plan_type: PlanType = PlanType.PPO
    holder_name: str  # subscriber
    start_date: date  # coverage effective date
    end_date: date  # coverage termination date
    waiting_period_days: int = 0  # eligibility waiting period (ACA caps it at 90 days)
    timely_filing_days: int = 180  # claims must be filed within this many days of discharge
    deductible: float = 0.0
    deductible_met: float = 0.0
    coinsurance_pct: float = 0.0  # member share after the deductible
    oop_max: float = 0.0  # annual out-of-pocket maximum
    oop_met: float = 0.0
    preauth_required_above: float = 50_000.0
    preauth_keywords: list[str] = Field(
        default_factory=list
    )  # services that always need prior auth
    exclusions: list[Exclusion] = Field(default_factory=list)
    benefit_limits: list[BenefitLimit] = Field(default_factory=list)
    network_providers: list[str] = Field(default_factory=list)
    required_documents: list[DocumentType] = Field(
        default_factory=lambda: [DocumentType.HOSPITAL_BILL, DocumentType.DISCHARGE_SUMMARY]
    )


# --------------------------------------------------------------------------- analysis


class RuleResult(BaseModel):
    rule_id: str
    title: str
    status: RuleStatus
    severity: Severity = Severity.INFO
    message: str
    clause: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class RiskReason(BaseModel):
    feature: str
    contribution: float  # log-odds contribution from the tree model (TreeSHAP)
    direction: str  # "increases" | "decreases"
    text: str


class RiskScore(BaseModel):
    probability: float  # calibrated P(claim is pended, denied or reduced on first adjudication)
    band: RiskBand
    reasons: list[RiskReason] = Field(default_factory=list)
    model_version: str


class AnomalyFlag(BaseModel):
    code: str
    description: str
    score: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)


class ClaimAnalysis(BaseModel):
    claim_id: str
    extracted: ExtractedClaimData
    rules: list[RuleResult] = Field(default_factory=list)
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    risk: RiskScore | None = None
    missing_documents: list[DocumentType] = Field(default_factory=list)
    features: dict[str, float | None] = Field(default_factory=dict)  # model inputs, kept for audit
    summary: str = ""
    suggested_route: str = "review"  # "review" | "request_info"; never an approval or rejection
    pipeline_version: str = "0.1.0"
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- claim


class DocumentRef(BaseModel):
    document_id: str = Field(default_factory=lambda: new_id("doc"))
    filename: str
    content_type: str
    blob_path: str
    sha256: str
    size_bytes: int
    doc_type: DocumentType | None = None
    uploaded_at: datetime = Field(default_factory=utcnow)


class ReviewerDecision(BaseModel):
    decision: DecisionType
    reviewer_id: str
    note: str = ""
    decided_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(use_enum_values=False)


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: new_id("clm"))
    tenant_id: str
    policy_id: str
    submitted_by: str
    consent_given: bool
    status: ClaimStatus = ClaimStatus.RECEIVED
    documents: list[DocumentRef] = Field(default_factory=list)
    analysis: ClaimAnalysis | None = None
    decision: ReviewerDecision | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    tenant_id: str
    actor: str
    action: str
    resource: str
    at: datetime = Field(default_factory=utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class ClaimJob(BaseModel):
    """Queue message. Carries ids only: never document content or personal data."""

    tenant_id: str
    claim_id: str
    attempt: int = 0
