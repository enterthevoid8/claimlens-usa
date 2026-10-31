"""Worker-side processing: one claim, idempotent, never raises for a bad document."""

from __future__ import annotations

import logging

from claimlens.analysis import analyse_claim
from claimlens.container import Container
from claimlens.domain.models import AuditEvent, Claim, ClaimStatus, DocumentType, utcnow
from claimlens.errors import NotFound
from claimlens.extraction.classify import classify_document
from claimlens.extraction.extract import DocText
from claimlens.extraction.layout import UnsupportedDocument
from claimlens.rag.chunk import chunk_policy_wording
from claimlens.rag.wording import render_policy_wording

log = logging.getLogger(__name__)


def ensure_policy_indexed(c: Container, tenant_id: str, policy_id: str) -> None:
    if c.index.has_policy(tenant_id, policy_id):
        return
    policy = c.repo.get_policy(tenant_id, policy_id)
    if policy is None:
        return
    c.index.index(
        chunk_policy_wording(
            render_policy_wording(policy), tenant_id=tenant_id, policy_id=policy_id
        )
    )


def register_policy(c: Container, policy) -> None:  # type: ignore[no-untyped-def]
    c.repo.save_policy(policy)
    c.index.index(
        chunk_policy_wording(
            render_policy_wording(policy), tenant_id=policy.tenant_id, policy_id=policy.policy_id
        )
    )


def process_claim(c: Container, tenant_id: str, claim_id: str) -> Claim:
    claim = c.repo.get_claim(tenant_id, claim_id)
    if claim is None:
        raise NotFound("claim not found")
    if claim.status == ClaimStatus.DECIDED:
        return claim  # idempotent: a redelivered message must not reopen a decided claim
    claim.status = ClaimStatus.PROCESSING
    claim.updated_at = utcnow()
    c.repo.save_claim(claim)

    policy = c.repo.get_policy(tenant_id, claim.policy_id)
    if policy is None:
        return _fail(c, claim, "policy not found")
    ensure_policy_indexed(c, tenant_id, claim.policy_id)

    docs: list[DocText] = []
    unreadable: list[str] = []
    for ref in claim.documents:
        try:
            layout = c.layout.analyze(c.blobs.get(ref.blob_path), ref.content_type)
        except UnsupportedDocument as exc:
            unreadable.append(f"{ref.filename}: {exc}")
            ref.doc_type = DocumentType.OTHER
            continue
        ref.doc_type = classify_document(layout.text, ref.filename)
        docs.append(DocText(document_id=ref.document_id, doc_type=ref.doc_type, text=layout.text))

    analysis = analyse_claim(
        claim_id=claim.claim_id,
        policy=policy,
        docs=docs,
        refs=claim.documents,
        extractor=c.extractor,
        models=c.models,
        unreadable=unreadable,
    )
    claim.analysis = analysis
    claim.status = (
        ClaimStatus.NEEDS_INFO if analysis.suggested_route == "request_info" else ClaimStatus.READY
    )
    claim.error = None
    claim.updated_at = utcnow()
    c.repo.save_claim(claim)
    c.audit.append(
        AuditEvent(
            tenant_id=tenant_id,
            actor="system:worker",
            action="claim.analysed",
            resource=claim_id,
            details={
                "route": analysis.suggested_route,
                "risk_band": analysis.risk.band.value if analysis.risk else None,
                "model_version": analysis.risk.model_version if analysis.risk else None,
                "extractor": analysis.extracted.extractor,
            },
        )
    )
    return claim


def _fail(c: Container, claim: Claim, reason: str) -> Claim:
    claim.status = ClaimStatus.FAILED
    claim.error = reason
    claim.updated_at = utcnow()
    c.repo.save_claim(claim)
    c.audit.append(
        AuditEvent(
            tenant_id=claim.tenant_id,
            actor="system:worker",
            action="claim.failed",
            resource=claim.claim_id,
            details={"reason": reason},
        )
    )
    return claim


def mark_failed(c: Container, tenant_id: str, claim_id: str, reason: str) -> None:
    claim = c.repo.get_claim(tenant_id, claim_id)
    if claim is not None and claim.status != ClaimStatus.DECIDED:
        _fail(c, claim, reason)


def run_worker_once(c: Container, max_messages: int = 5) -> int:
    """Pull a batch, process each, and settle each message. Returns the number of messages handled."""
    handled = 0
    for received in c.queue.receive(max_messages):
        handled += 1
        job = received.job
        try:
            process_claim(c, job.tenant_id, job.claim_id)
            c.queue.complete(received)
        except NotFound:
            c.queue.dead_letter(received, "claim not found")
        except Exception as exc:
            log.exception(
                "processing failed for claim %s (delivery %s)",
                job.claim_id,
                received.delivery_count,
            )
            if received.delivery_count >= c.settings.max_job_attempts:
                mark_failed(
                    c,
                    job.tenant_id,
                    job.claim_id,
                    "processing failed repeatedly; a person will look at it",
                )
                c.queue.dead_letter(received, type(exc).__name__)
            else:
                c.queue.abandon(received)
    return handled
