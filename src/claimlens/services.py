"""Application services: authorisation, validation, audit. Used by the API; framework-free so it is easy to test."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from claimlens.container import Container
from claimlens.domain.models import (
    AnomalyFlag,
    AuditEvent,
    Claim,
    ClaimJob,
    ClaimStatus,
    DecisionType,
    DocumentRef,
    DocumentType,
    ExtractedClaimData,
    ReviewerDecision,
    RiskScore,
    Role,
    RuleResult,
    new_id,
    utcnow,
)
from claimlens.errors import BadRequest, Conflict, Forbidden, NotFound, PayloadTooLarge
from claimlens.extraction.layout import ALLOWED_TYPES, sniff_content_type
from claimlens.process import ensure_policy_indexed
from claimlens.rag.answer import answer_question
from claimlens.security import safe_id


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    role: Role


# ------------------------------------------------------------------ response views (role-filtered)


class DocumentView(BaseModel):
    document_id: str
    filename: str
    doc_type: DocumentType | None
    size_bytes: int


class AnalysisView(BaseModel):
    summary: str
    suggested_route: str
    rules: list[RuleResult]
    missing_documents: list[DocumentType]


class ReviewerAnalysisView(AnalysisView):
    risk: RiskScore | None
    anomalies: list[AnomalyFlag]
    extracted: ExtractedClaimData
    features: dict[str, float | None]


class ClaimView(BaseModel):
    claim_id: str
    policy_id: str
    status: ClaimStatus
    created_at: Any
    documents: list[DocumentView]
    analysis: AnalysisView | ReviewerAnalysisView | None = None
    decision: ReviewerDecision | None = None
    error: str | None = None


def to_view(claim: Claim, role: Role) -> ClaimView:
    """Patients and providers never see risk scores, anomaly flags or raw features: they could be gamed."""
    analysis: AnalysisView | ReviewerAnalysisView | None = None
    a = claim.analysis
    if a is not None:
        base = {
            "summary": a.summary,
            "suggested_route": a.suggested_route,
            "rules": a.rules,
            "missing_documents": a.missing_documents,
        }
        if role == Role.REVIEWER:
            analysis = ReviewerAnalysisView(
                **base,
                risk=a.risk,
                anomalies=a.anomalies,
                extracted=a.extracted,
                features=a.features,
            )
        else:
            analysis = AnalysisView(**base)
    return ClaimView(
        claim_id=claim.claim_id,
        policy_id=claim.policy_id,
        status=claim.status,
        created_at=claim.created_at,
        documents=[
            DocumentView(
                document_id=d.document_id,
                filename=d.filename,
                doc_type=d.doc_type,
                size_bytes=d.size_bytes,
            )
            for d in claim.documents
        ],
        analysis=analysis,
        decision=claim.decision,
        error=claim.error,
    )


class QueueItem(BaseModel):
    claim_id: str
    status: ClaimStatus
    created_at: Any
    risk_probability: float | None
    risk_band: str | None
    top_reason: str | None
    n_flags: int
    route: str | None


class AnswerView(BaseModel):
    answer: str
    refused: bool
    citations: list[dict[str, str]]


# ------------------------------------------------------------------ service


class ClaimService:
    def __init__(self, c: Container) -> None:
        self.c = c

    # --- helpers
    def _audit(self, p: Principal, action: str, resource: str, **details: Any) -> None:
        self.c.audit.append(
            AuditEvent(
                tenant_id=p.tenant_id,
                actor=f"{p.role.value}:{p.subject}",
                action=action,
                resource=resource,
                details=details,
            )
        )

    def _load(self, p: Principal, claim_id: str) -> Claim:
        """Tenant is part of every lookup. Other users' claims look exactly like missing claims."""
        try:
            claim = self.c.repo.get_claim(p.tenant_id, safe_id(claim_id, "claim"))
        except ValueError:
            claim = None
        if claim is None or (p.role != Role.REVIEWER and claim.submitted_by != p.subject):
            raise NotFound("claim not found")
        return claim

    # --- commands
    def create_claim(self, p: Principal, policy_id: str, consent_given: bool) -> Claim:
        if p.role == Role.REVIEWER:
            raise Forbidden("reviewers cannot submit claims")
        if not consent_given:
            raise BadRequest("consent to process the claim documents is required")
        try:
            policy = self.c.repo.get_policy(p.tenant_id, safe_id(policy_id, "policy"))
        except ValueError:
            policy = None
        if policy is None:
            raise NotFound("policy not found")
        claim = Claim(
            tenant_id=p.tenant_id, policy_id=policy_id, submitted_by=p.subject, consent_given=True
        )
        self.c.repo.save_claim(claim)
        self._audit(p, "claim.created", claim.claim_id, policy_id=policy_id)
        return claim

    def add_document(
        self, p: Principal, claim_id: str, filename: str, declared_type: str, data: bytes
    ) -> DocumentRef:
        claim = self._load(p, claim_id)
        if p.role == Role.REVIEWER:
            raise Forbidden("reviewers cannot upload documents")
        if claim.status not in (ClaimStatus.RECEIVED, ClaimStatus.NEEDS_INFO):
            raise Conflict(
                "documents can only be added before processing or when more information is requested"
            )
        if len(claim.documents) >= self.c.settings.max_documents_per_claim:
            raise BadRequest("too many documents on this claim")
        if not data:
            raise BadRequest("empty file")
        if len(data) > self.c.settings.max_upload_bytes:
            raise PayloadTooLarge("file is too large")
        content_type = sniff_content_type(data, declared_type)
        if content_type not in ALLOWED_TYPES:
            raise BadRequest("unsupported file type; upload a PDF, image or text file")
        doc_id = new_id("doc")
        path = f"raw/{p.tenant_id}/{claim.claim_id}/{doc_id}"
        self.c.blobs.put(path, data, content_type)
        ref = DocumentRef(
            document_id=doc_id,
            filename=_clean_filename(filename),
            content_type=content_type,
            blob_path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        claim.documents.append(ref)
        claim.updated_at = utcnow()
        self.c.repo.save_claim(claim)
        self._audit(
            p,
            "document.uploaded",
            claim.claim_id,
            document_id=doc_id,
            size=len(data),
            content_type=content_type,
        )
        return ref

    def submit(self, p: Principal, claim_id: str) -> Claim:
        claim = self._load(p, claim_id)
        if p.role == Role.REVIEWER:
            raise Forbidden("reviewers cannot submit claims")
        if not claim.documents:
            raise BadRequest("upload at least one document first")
        if claim.status in (ClaimStatus.PROCESSING, ClaimStatus.DECIDED):
            raise Conflict(f"claim is {claim.status.value}")
        claim.status = ClaimStatus.RECEIVED
        claim.updated_at = utcnow()
        self.c.repo.save_claim(claim)
        self.c.queue.send(ClaimJob(tenant_id=claim.tenant_id, claim_id=claim.claim_id))
        self._audit(p, "claim.submitted", claim.claim_id, documents=len(claim.documents))
        return claim

    def get_claim(self, p: Principal, claim_id: str) -> ClaimView:
        return to_view(self._load(p, claim_id), p.role)

    def list_claims(self, p: Principal) -> list[ClaimView]:
        by = None if p.role == Role.REVIEWER else p.subject
        return [to_view(c, p.role) for c in self.c.repo.list_claims(p.tenant_id, submitted_by=by)]

    def reviewer_queue(self, p: Principal) -> list[QueueItem]:
        if p.role != Role.REVIEWER:
            raise Forbidden("reviewer access required")
        items: list[QueueItem] = []
        for st in (ClaimStatus.READY, ClaimStatus.NEEDS_INFO):
            for c in self.c.repo.list_claims(p.tenant_id, status=st):
                a = c.analysis
                r = a.risk if a else None
                items.append(
                    QueueItem(
                        claim_id=c.claim_id,
                        status=c.status,
                        created_at=c.created_at,
                        risk_probability=r.probability if r else None,
                        risk_band=r.band.value if r else None,
                        top_reason=r.reasons[0].text if r and r.reasons else None,
                        n_flags=(len(a.anomalies) + sum(x.status.value == "fail" for x in a.rules))
                        if a
                        else 0,
                        route=a.suggested_route if a else None,
                    )
                )
        # highest modelled risk first; unscored claims sort after scored ones but ahead of nothing: they still need a human
        return sorted(
            items, key=lambda i: (i.risk_probability is None, -(i.risk_probability or 0.0))
        )

    def explain(self, p: Principal, claim_id: str, question: str) -> AnswerView:
        claim = self._load(p, claim_id)
        if not question.strip():
            raise BadRequest("question is empty")
        ensure_policy_indexed(self.c, claim.tenant_id, claim.policy_id)
        ans = answer_question(
            self.c.index,
            tenant_id=claim.tenant_id,
            policy_id=claim.policy_id,
            question=question,
            analysis=claim.analysis,
            generator=self.c.generator,
        )
        self._audit(
            p,
            "claim.explain",
            claim.claim_id,
            refused=ans.refused,
            used_llm=ans.used_llm,
            clauses=[x.clause for x in ans.citations],
        )
        return AnswerView(
            answer=ans.text,
            refused=ans.refused,
            citations=[
                {"clause": x.clause, "title": x.title, "quote": x.quote} for x in ans.citations
            ],
        )

    def decide(self, p: Principal, claim_id: str, decision: DecisionType, note: str) -> Claim:
        if p.role != Role.REVIEWER:
            raise Forbidden("reviewer access required")
        claim = self._load(p, claim_id)
        if claim.status not in (ClaimStatus.READY, ClaimStatus.NEEDS_INFO):
            raise Conflict("claim is not ready for a decision")
        if decision == DecisionType.DENY and not note.strip():
            raise BadRequest("a reason is required when denying a claim")
        claim.decision = ReviewerDecision(
            decision=decision, reviewer_id=p.subject, note=note.strip()[:2000]
        )
        claim.status = (
            ClaimStatus.NEEDS_INFO if decision == DecisionType.REQUEST_INFO else ClaimStatus.DECIDED
        )
        claim.updated_at = utcnow()
        self.c.repo.save_claim(claim)
        a = claim.analysis
        self._audit(  # outcome + what the human saw: this is the feedback loop for monitoring and retraining
            p,
            "claim.decided",
            claim.claim_id,
            decision=decision.value,
            risk_band=a.risk.band.value if a and a.risk else None,
            risk_probability=a.risk.probability if a and a.risk else None,
            model_version=a.risk.model_version if a and a.risk else None,
        )
        return claim

    def delete_claim(self, p: Principal, claim_id: str) -> None:
        """Consent withdrawal / erasure: documents, claim record and audit-safe tombstone (no personal data)."""
        claim = self._load(p, claim_id)
        if p.role != Role.REVIEWER and claim.submitted_by != p.subject:
            raise Forbidden("not allowed")
        self.c.blobs.delete_prefix(f"raw/{claim.tenant_id}/{claim.claim_id}")
        self.c.repo.delete_claim(claim.tenant_id, claim.claim_id)
        self._audit(p, "claim.deleted", claim.claim_id)


def _clean_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    return base[:120] or "document"
