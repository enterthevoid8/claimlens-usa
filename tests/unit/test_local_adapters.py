import time

import pytest

from claimlens.adapters.local import LocalAuditLog, LocalClaimRepository, LocalJobQueue
from claimlens.domain.models import AuditEvent, Claim, ClaimJob, ClaimStatus


def test_queue_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    q = LocalJobQueue(tmp_path)
    q.send(ClaimJob(tenant_id="t1", claim_id="c1"))
    [m] = q.receive()
    assert m.job.claim_id == "c1" and q.receive() == []  # in flight: invisible to other consumers
    q.complete(m)
    assert q.pending_count() == 0 and q.receive() == []


def test_abandon_requeues_with_incremented_attempt_and_deadletter_keeps_reason(tmp_path) -> None:  # type: ignore[no-untyped-def]
    q = LocalJobQueue(tmp_path)
    q.send(ClaimJob(tenant_id="t1", claim_id="c1"))
    [m] = q.receive()
    q.abandon(m)
    [m2] = q.receive()
    assert m2.delivery_count == 2
    q.dead_letter(m2, "boom")
    assert q.dead_count() == 1 and q.pending_count() == 0


def test_expired_inflight_messages_come_back(tmp_path) -> None:  # type: ignore[no-untyped-def]
    q = LocalJobQueue(tmp_path, visibility_timeout_s=0.05)
    q.send(ClaimJob(tenant_id="t1", claim_id="c1"))
    assert len(q.receive()) == 1
    time.sleep(0.1)
    assert len(q.receive()) == 1  # a crashed worker does not lose the claim


def test_repository_scopes_by_tenant_and_validates_ids(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo = LocalClaimRepository(tmp_path)
    c = Claim(tenant_id="t1", policy_id="p", submitted_by="u1", consent_given=True)
    repo.save_claim(c)
    assert repo.get_claim("t1", c.claim_id) is not None
    assert repo.get_claim("t2", c.claim_id) is None  # same id, other tenant
    assert repo.list_claims("t2") == []
    assert (
        repo.list_claims("t1", status=ClaimStatus.RECEIVED, submitted_by="u1")[0].claim_id
        == c.claim_id
    )
    assert repo.list_claims("t1", submitted_by="someone-else") == []
    for bad in ("../x", "a/b", ""):
        with pytest.raises(ValueError):
            repo.get_claim("t1", bad)
        with pytest.raises(ValueError):
            repo.get_claim(bad, "c")
    assert repo.delete_claim("t1", c.claim_id) and not repo.delete_claim("t1", c.claim_id)


def test_audit_log_filters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    log = LocalAuditLog(tmp_path)
    log.append(AuditEvent(tenant_id="t1", actor="a", action="x", resource="r1"))
    log.append(AuditEvent(tenant_id="t2", actor="a", action="x", resource="r1"))
    assert len(log.list_events("t1")) == 1 and log.list_events("t1", resource="nope") == []
