from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from claimlens.container import Container
from claimlens.domain.models import ClaimStatus, Role
from claimlens.process import run_worker_once
from claimlens.synthetic.generator import SyntheticCase
from tests.conftest import auth, make_token

HOSP = ("hosp-1", "t1", Role.PROVIDER)
PAT = ("pat-1", "t1", Role.PATIENT)
REV = ("rev-1", "t1", Role.REVIEWER)


def create_and_submit(client: TestClient, case: SyntheticCase, who=HOSP) -> str:  # type: ignore[no-untyped-def]
    h = auth(*who)
    r = client.post(
        "/v1/claims", json={"policy_id": case.policy.policy_id, "consent_given": True}, headers=h
    )
    assert r.status_code == 201, r.text
    cid = r.json()["claim_id"]
    for name, text in case.documents.items():
        up = client.post(
            f"/v1/claims/{cid}/documents",
            files={"file": (name, io.BytesIO(text.encode()), "text/plain")},
            headers=h,
        )
        assert up.status_code == 201, up.text
    assert client.post(f"/v1/claims/{cid}/submit", headers=h).status_code == 202
    return cid


def test_full_flow(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    cid = create_and_submit(client, seeded)
    assert client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).json()["status"] == "received"
    assert run_worker_once(container) == 1
    v = client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).json()
    assert v["status"] in ("ready", "needs_info") and v["analysis"]["rules"]
    queue = client.get("/v1/reviewer/queue", headers=auth(*REV)).json()
    assert [q["claim_id"] for q in queue] == [cid]
    d = client.post(
        f"/v1/claims/{cid}/decision", json={"decision": "approve", "note": "ok"}, headers=auth(*REV)
    )
    assert d.status_code == 200 and d.json()["status"] == "decided"
    assert client.get("/v1/reviewer/queue", headers=auth(*REV)).json() == []


def test_patients_and_providers_never_see_risk_or_anomalies(
    client: TestClient, container: Container, seeded: SyntheticCase
) -> None:
    cid = create_and_submit(client, seeded)
    run_worker_once(container)
    patient_view = client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).json()["analysis"]
    reviewer_view = client.get(f"/v1/claims/{cid}", headers=auth(*REV)).json()["analysis"]
    for forbidden in ("risk", "anomalies", "features", "extracted"):
        assert forbidden not in patient_view
        assert forbidden in reviewer_view


def test_tenant_isolation(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    cid = create_and_submit(client, seeded)
    run_worker_once(container)
    other_reviewer = auth("rev-9", "t2", Role.REVIEWER)
    assert client.get(f"/v1/claims/{cid}", headers=other_reviewer).status_code == 404
    assert client.get("/v1/reviewer/queue", headers=other_reviewer).json() == []
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "approve"}, headers=other_reviewer
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/claims/{cid}", headers=other_reviewer).status_code == 404
    assert (
        client.post(
            f"/v1/claims/{cid}/explain", json={"question": "room rent"}, headers=other_reviewer
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/claims",
            json={"policy_id": seeded.policy.policy_id, "consent_given": True},
            headers=auth("h", "t2", Role.PROVIDER),
        ).status_code
        == 404
    )  # policy belongs to t1


def test_users_only_see_their_own_claims(
    client: TestClient, container: Container, seeded: SyntheticCase
) -> None:
    cid = create_and_submit(client, seeded, who=HOSP)
    assert (
        client.get(f"/v1/claims/{cid}", headers=auth("hosp-2", "t1", Role.PROVIDER)).status_code
        == 404
    )
    assert client.get(f"/v1/claims/{cid}", headers=auth(*PAT)).status_code == 404
    assert client.get("/v1/claims", headers=auth("hosp-2", "t1", Role.PROVIDER)).json() == []
    assert len(client.get("/v1/claims", headers=auth(*REV)).json()) == 1


def test_role_restrictions(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    cid = create_and_submit(client, seeded)
    run_worker_once(container)
    assert client.get("/v1/reviewer/queue", headers=auth(*HOSP)).status_code == 403
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "approve"}, headers=auth(*HOSP)
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/claims",
            json={"policy_id": seeded.policy.policy_id, "consent_given": True},
            headers=auth(*REV),
        ).status_code
        == 403
    )
    up = client.post(
        f"/v1/claims/{cid}/documents",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=auth(*REV),
    )
    assert up.status_code == 403


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"}]
)
def test_unauthenticated(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/v1/claims", headers=headers).status_code == 401


def test_token_validation(client: TestClient) -> None:
    ok = {"Authorization": f"Bearer {make_token('u', 't1', Role.PROVIDER)}"}
    assert client.get("/v1/claims", headers=ok).status_code == 200
    wrong_secret = {
        "Authorization": f"Bearer {make_token('u', 't1', Role.PROVIDER, secret='x' * 40)}"
    }
    expired = {
        "Authorization": f"Bearer {make_token('u', 't1', Role.PROVIDER, expires=-__import__('datetime').timedelta(hours=1))}"
    }
    no_role = {
        "Authorization": f"Bearer {__import__('jwt').encode({'sub': 'u', 'tenant_id': 't1', 'roles': [], 'aud': 'claimlens-dev', 'exp': 9999999999}, 'dev-only-secret-change-me-0123456789abcdef', algorithm='HS256')}"
    }
    two_roles = {
        "Authorization": f"Bearer {__import__('jwt').encode({'sub': 'u', 'tenant_id': 't1', 'roles': ['reviewer', 'patient'], 'aud': 'claimlens-dev', 'exp': 9999999999}, 'dev-only-secret-change-me-0123456789abcdef', algorithm='HS256')}"
    }
    bad_tenant = {"Authorization": f"Bearer {make_token('u', '../t1', Role.PROVIDER)}"}
    none_alg = {
        "Authorization": "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ1Iiwicm9sZXMiOlsicmV2aWV3ZXIiXX0."
    }
    for h in (wrong_secret, expired, no_role, two_roles, bad_tenant, none_alg):
        assert client.get("/v1/claims", headers=h).status_code == 401


def test_consent_is_required(client: TestClient, seeded: SyntheticCase) -> None:
    r = client.post(
        "/v1/claims",
        json={"policy_id": seeded.policy.policy_id, "consent_given": False},
        headers=auth(*HOSP),
    )
    assert r.status_code == 400 and "consent" in r.json()["detail"]


def test_upload_validation(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    h = auth(*HOSP)
    cid = client.post(
        "/v1/claims", json={"policy_id": seeded.policy.policy_id, "consent_given": True}, headers=h
    ).json()["claim_id"]
    url = f"/v1/claims/{cid}/documents"
    assert (
        client.post(url, files={"file": ("a.txt", b"", "text/plain")}, headers=h).status_code == 400
    )
    assert (
        client.post(
            url,
            files={"file": ("a.exe", b"MZ\x90\x00binary", "application/octet-stream")},
            headers=h,
        ).status_code
        == 400
    )
    assert (
        client.post(
            url, files={"file": ("a.txt", b"\xff\xfe\x00bad", "text/plain")}, headers=h
        ).status_code
        == 400
    )
    big = b"a" * (container.settings.max_upload_bytes + 1)
    assert (
        client.post(url, files={"file": ("big.txt", big, "text/plain")}, headers=h).status_code
        == 413
    )
    # a script claiming to be a PDF is rejected by magic bytes, and a real PDF header is detected regardless of the declared type
    assert (
        client.post(
            url,
            files={"file": ("a.pdf", b"<script>alert(1)</script>", "application/pdf")},
            headers=h,
        ).status_code
        == 400
    )
    ok = client.post(
        url, files={"file": ("../../etc/passwd.txt", b"Final Bill", "text/plain")}, headers=h
    )
    assert ok.status_code == 201 and ok.json()["filename"] == "passwd.txt"  # path stripped


def test_document_limit(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    h = auth(*HOSP)
    cid = client.post(
        "/v1/claims", json={"policy_id": seeded.policy.policy_id, "consent_given": True}, headers=h
    ).json()["claim_id"]
    for i in range(container.settings.max_documents_per_claim):
        assert (
            client.post(
                f"/v1/claims/{cid}/documents",
                files={"file": (f"{i}.txt", b"x", "text/plain")},
                headers=h,
            ).status_code
            == 201
        )
    assert (
        client.post(
            f"/v1/claims/{cid}/documents", files={"file": ("n.txt", b"x", "text/plain")}, headers=h
        ).status_code
        == 400
    )


def test_submit_requires_documents(client: TestClient, seeded: SyntheticCase) -> None:
    h = auth(*HOSP)
    cid = client.post(
        "/v1/claims", json={"policy_id": seeded.policy.policy_id, "consent_given": True}, headers=h
    ).json()["claim_id"]
    assert client.post(f"/v1/claims/{cid}/submit", headers=h).status_code == 400


def test_decision_rules(client: TestClient, container: Container, seeded: SyntheticCase) -> None:
    cid = create_and_submit(client, seeded)
    rev = auth(*REV)
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "approve"}, headers=rev
        ).status_code
        == 409
    )  # not analysed yet
    run_worker_once(container)
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "deny", "note": " "}, headers=rev
        ).status_code
        == 400
    )  # reasons are mandatory
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "maybe"}, headers=rev
        ).status_code
        == 422
    )
    ok = client.post(
        f"/v1/claims/{cid}/decision",
        json={"decision": "deny", "note": "Excluded under clause 3.1"},
        headers=rev,
    )
    assert ok.status_code == 200 and ok.json()["decision"]["reviewer_id"] == "rev-1"
    assert (
        client.post(
            f"/v1/claims/{cid}/decision", json={"decision": "approve"}, headers=rev
        ).status_code
        == 409
    )  # decided is final
    audit = container.audit.list_events("t1", resource=cid)
    assert [e.action for e in audit][-1] == "claim.decided" and audit[-1].actor == "reviewer:rev-1"


def test_nothing_can_decide_a_claim_except_the_reviewer_endpoint(
    client: TestClient, container: Container, seeded: SyntheticCase
) -> None:
    cid = create_and_submit(client, seeded)
    run_worker_once(container)
    claim = container.repo.get_claim("t1", cid)
    assert claim is not None and claim.decision is None and claim.status != ClaimStatus.DECIDED


def test_explain_grounded_and_refuses(
    client: TestClient, container: Container, seeded: SyntheticCase
) -> None:
    cid = create_and_submit(client, seeded)
    run_worker_once(container)
    h = auth(*HOSP)
    r = client.post(
        f"/v1/claims/{cid}/explain", json={"question": "What is my deductible?"}, headers=h
    ).json()
    assert not r["refused"] and r["citations"][0]["clause"] == "1.1"
    r = client.post(
        f"/v1/claims/{cid}/explain", json={"question": "Who won the Super Bowl?"}, headers=h
    ).json()
    assert r["refused"] and r["citations"] == []
    assert (
        client.post(f"/v1/claims/{cid}/explain", json={"question": ""}, headers=h).status_code
        == 422
    )
    assert (
        client.post(
            f"/v1/claims/{cid}/explain", json={"question": "x" * 501}, headers=h
        ).status_code
        == 422
    )


def test_delete_removes_documents_and_record_and_leaves_a_clean_audit_trail(
    client: TestClient, container: Container, seeded: SyntheticCase
) -> None:
    cid = create_and_submit(client, seeded)
    claim = container.repo.get_claim("t1", cid)
    assert claim is not None
    path = claim.documents[0].blob_path
    assert client.delete(f"/v1/claims/{cid}", headers=auth(*HOSP)).status_code == 204
    assert client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).status_code == 404
    with pytest.raises(FileNotFoundError):
        container.blobs.get(path)
    events = container.audit.list_events("t1", resource=cid)
    assert events[-1].action == "claim.deleted"
    assert all(
        "Aditya" not in str(e.details) and seeded.truth_bill.patient_name not in str(e.details)
        for e in events
    )  # no personal data in audit details


def test_rate_limit(client: TestClient) -> None:
    from claimlens_api import main

    h = auth("burst", "t1", Role.PROVIDER)
    main.explain_limit.hits.clear()
    codes = [
        client.post("/v1/claims/clm_x/explain", json={"question": "q"}, headers=h).status_code
        for _ in range(25)
    ]
    assert codes.count(429) >= 4 and codes[0] == 404
    main.explain_limit.hits.clear()


def test_errors_do_not_leak_internals(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        container.repo,
        "list_claims",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret connection string xyz")),
    )
    with TestClient(client.app, raise_server_exceptions=False) as tc:
        r = tc.get("/v1/claims", headers=auth(*HOSP))
    assert r.status_code == 500 and "xyz" not in r.text and r.json() == {"detail": "internal error"}


def test_security_headers_and_health(client: TestClient) -> None:
    r = client.get("/healthz")
    assert (
        r.status_code == 200
        and r.headers["x-content-type-options"] == "nosniff"
        and r.headers["cache-control"] == "no-store"
    )
    assert client.get("/readyz").json()["status"] == "ok"


def test_inline_processing_flag(
    client: TestClient, container: Container, seeded: SyntheticCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    from claimlens.settings import get_settings

    monkeypatch.setattr(get_settings(), "inline_processing", True)
    cid = create_and_submit(client, seeded)
    for _ in range(50):
        if client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).json()["status"] != "received":
            break
        time.sleep(0.05)
    assert client.get(f"/v1/claims/{cid}", headers=auth(*HOSP)).json()["status"] in (
        "ready",
        "needs_info",
    )
