from __future__ import annotations

import pytest

from claimlens.container import Container
from claimlens.domain.models import ClaimJob, ClaimStatus, Role
from claimlens.process import process_claim, run_worker_once
from claimlens.services import ClaimService, Principal
from claimlens.synthetic.generator import SyntheticCase

HOSP = Principal("hosp-1", "t1", Role.PROVIDER)
REV = Principal("rev-1", "t1", Role.REVIEWER)


def submit(c: Container, case: SyntheticCase) -> str:
    svc = ClaimService(c)
    cl = svc.create_claim(HOSP, case.policy.policy_id, True)
    for n, t in case.documents.items():
        svc.add_document(HOSP, cl.claim_id, n, "text/plain", t.encode())
    svc.submit(HOSP, cl.claim_id)
    return cl.claim_id


def test_redelivery_does_not_reopen_a_decided_claim(
    container: Container, seeded: SyntheticCase
) -> None:
    cid = submit(container, seeded)
    run_worker_once(container)
    ClaimService(container).decide(
        REV,
        cid,
        __import__("claimlens.domain.models", fromlist=["DecisionType"]).DecisionType.APPROVE,
        "",
    )
    container.queue.send(ClaimJob(tenant_id="t1", claim_id=cid))  # duplicate delivery
    run_worker_once(container)
    claim = container.repo.get_claim("t1", cid)
    assert claim is not None and claim.status == ClaimStatus.DECIDED


def test_processing_is_idempotent(container: Container, seeded: SyntheticCase) -> None:
    cid = submit(container, seeded)
    run_worker_once(container)
    first = container.repo.get_claim("t1", cid)
    process_claim(container, "t1", cid)
    second = container.repo.get_claim("t1", cid)
    assert first is not None and second is not None
    assert [(r.rule_id, r.status) for r in first.analysis.rules] == [
        (r.rule_id, r.status) for r in second.analysis.rules
    ]  # type: ignore[union-attr]


def test_poison_message_is_retried_then_dead_lettered_and_claim_marked_failed(
    container: Container, seeded: SyntheticCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = submit(container, seeded)

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("parser exploded on /home/secret/path")

    monkeypatch.setattr("claimlens.process.analyse_claim", boom)
    for _ in range(container.settings.max_job_attempts):
        run_worker_once(container)
    assert container.queue.dead_count() == 1 and container.queue.pending_count() == 0  # type: ignore[attr-defined]
    claim = container.repo.get_claim("t1", cid)
    assert claim is not None and claim.status == ClaimStatus.FAILED
    assert "secret" not in (claim.error or "")  # stored error is generic


def test_unknown_claim_is_dead_lettered(container: Container) -> None:
    container.queue.send(ClaimJob(tenant_id="t1", claim_id="clm_missing"))
    run_worker_once(container)
    assert container.queue.dead_count() == 1  # type: ignore[attr-defined]


def test_unreadable_document_becomes_a_finding_not_a_crash(
    container: Container, seeded: SyntheticCase
) -> None:
    svc = ClaimService(container)
    cl = svc.create_claim(HOSP, seeded.policy.policy_id, True)
    svc.add_document(HOSP, cl.claim_id, "scan.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    for n, t in seeded.documents.items():
        svc.add_document(HOSP, cl.claim_id, n, "text/plain", t.encode())
    svc.submit(HOSP, cl.claim_id)
    run_worker_once(container)
    claim = container.repo.get_claim("t1", cl.claim_id)
    assert claim is not None and claim.analysis is not None
    r017 = next(r for r in claim.analysis.rules if r.rule_id == "R017")
    assert r017.status.value == "fail" and "scan.png" in r017.message


def test_missing_documents_route_to_request_info(
    container: Container, seeded: SyntheticCase
) -> None:
    svc = ClaimService(container)
    cl = svc.create_claim(HOSP, seeded.policy.policy_id, True)
    svc.add_document(
        HOSP, cl.claim_id, "bill.txt", "text/plain", seeded.documents["bill.txt"].encode()
    )
    svc.submit(HOSP, cl.claim_id)
    run_worker_once(container)
    claim = container.repo.get_claim("t1", cl.claim_id)
    assert claim is not None and claim.status == ClaimStatus.NEEDS_INFO
    assert claim.analysis is not None and "discharge_summary" in [
        d.value for d in claim.analysis.missing_documents
    ]
