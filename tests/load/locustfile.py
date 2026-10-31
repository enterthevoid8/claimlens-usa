"""Load test:  locust -f tests/load/locustfile.py --host http://localhost:8000

Prerequisites: API running (`make api`), claims/policies loaded (`claimlens demo`), and tokens exported as
HOSPITAL_TOKEN / REVIEWER_TOKEN (see `claimlens token`). Measures the request path only: model inference runs in
the worker, so queue depth, not API latency, is the number to watch for processing throughput.
"""

from __future__ import annotations

import io
import os

from locust import HttpUser, between, task

POLICY_ID = os.environ.get("POLICY_ID", "POL000000")
BILL = "Sunrise Care Hospital\nFINAL BILL\nBill No: B-1\nPatient Name: Asha Rao\nDOA: 01/02/2025\nDOD: 03/02/2025\nDiagnosis: Dengue fever\n| Sr | Description | Qty | Rate | Amount |\n| 1 | Room rent - Semi private | 2 | 3000.00 | 6000.00 |\nGrand Total: 6000.00\n"


class Hospital(HttpUser):
    wait_time = between(1, 3)
    weight = 4

    def on_start(self) -> None:
        self.h = {"Authorization": f"Bearer {os.environ['HOSPITAL_TOKEN']}"}

    @task(3)
    def submit_claim(self) -> None:
        r = self.client.post(
            "/v1/claims",
            json={"policy_id": POLICY_ID, "consent_given": True},
            headers=self.h,
            name="create",
        )
        if r.status_code != 201:
            return
        cid = r.json()["claim_id"]
        self.client.post(
            f"/v1/claims/{cid}/documents",
            files={"file": ("bill.txt", io.BytesIO(BILL.encode()), "text/plain")},
            headers=self.h,
            name="upload",
        )
        self.client.post(f"/v1/claims/{cid}/submit", headers=self.h, name="submit")
        self.client.get(f"/v1/claims/{cid}", headers=self.h, name="poll")

    @task(1)
    def list_claims(self) -> None:
        self.client.get("/v1/claims", headers=self.h, name="list")


class Reviewer(HttpUser):
    wait_time = between(2, 5)
    weight = 1

    def on_start(self) -> None:
        self.h = {"Authorization": f"Bearer {os.environ['REVIEWER_TOKEN']}"}

    @task
    def queue(self) -> None:
        self.client.get("/v1/reviewer/queue", headers=self.h, name="queue")
