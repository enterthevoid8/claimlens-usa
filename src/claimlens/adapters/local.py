"""Filesystem-backed adapters for laptops, CI and docker-compose.

They are intentionally simple but safe: every id that becomes a path segment is validated, writes
are atomic (temp file + rename), and the queue claims messages with an atomic rename so an API
process and a worker process can share one volume.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from claimlens.adapters.ports import ReceivedJob
from claimlens.domain.models import AuditEvent, Claim, ClaimJob, ClaimStatus, Policy
from claimlens.security import safe_id


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = (root / "blobs").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        parts = [p for p in path.split("/") if p]
        if not parts or any(p in {".", ".."} or "\\" in p for p in parts):
            raise ValueError("invalid blob path")
        target = (self.root / Path(*parts)).resolve()
        if self.root not in target.parents:
            raise ValueError("invalid blob path")
        return target

    def put(self, path: str, data: bytes, content_type: str) -> None:
        _atomic_write(self._resolve(path), data)

    def get(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def delete_prefix(self, prefix: str) -> int:
        target = self._resolve(prefix)
        if not target.exists():
            return 0
        count = 0
        for p in sorted(target.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
                count += 1
            else:
                p.rmdir()
        target.rmdir()
        return count


class LocalClaimRepository:
    def __init__(self, root: Path) -> None:
        self.root = root / "db"
        self.root.mkdir(parents=True, exist_ok=True)

    def _claim_path(self, tenant_id: str, claim_id: str) -> Path:
        return (
            self.root
            / safe_id(tenant_id, "tenant")
            / "claims"
            / f"{safe_id(claim_id, 'claim')}.json"
        )

    def _policy_path(self, tenant_id: str, policy_id: str) -> Path:
        return (
            self.root
            / safe_id(tenant_id, "tenant")
            / "policies"
            / f"{safe_id(policy_id, 'policy')}.json"
        )

    def save_claim(self, claim: Claim) -> None:
        _atomic_write(
            self._claim_path(claim.tenant_id, claim.claim_id),
            claim.model_dump_json(indent=2).encode(),
        )

    def get_claim(self, tenant_id: str, claim_id: str) -> Claim | None:
        path = self._claim_path(tenant_id, claim_id)
        if not path.exists():
            return None
        return Claim.model_validate_json(path.read_text())

    def list_claims(
        self, tenant_id: str, status: ClaimStatus | None = None, submitted_by: str | None = None
    ) -> list[Claim]:
        folder = self.root / safe_id(tenant_id, "tenant") / "claims"
        if not folder.exists():
            return []
        out: list[Claim] = []
        for f in folder.glob("*.json"):
            claim = Claim.model_validate_json(f.read_text())
            if status and claim.status != status:
                continue
            if submitted_by and claim.submitted_by != submitted_by:
                continue
            out.append(claim)
        return sorted(out, key=lambda c: c.created_at)

    def delete_claim(self, tenant_id: str, claim_id: str) -> bool:
        path = self._claim_path(tenant_id, claim_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def save_policy(self, policy: Policy) -> None:
        _atomic_write(
            self._policy_path(policy.tenant_id, policy.policy_id),
            policy.model_dump_json(indent=2).encode(),
        )

    def get_policy(self, tenant_id: str, policy_id: str) -> Policy | None:
        path = self._policy_path(tenant_id, policy_id)
        if not path.exists():
            return None
        return Policy.model_validate_json(path.read_text())


class LocalJobQueue:
    """Directory queue: ``pending/`` -> ``inflight/`` (atomic rename) -> done, or ``dead/``."""

    def __init__(self, root: Path, visibility_timeout_s: float = 60.0) -> None:
        self.base = root / "queue"
        self.visibility_timeout_s = visibility_timeout_s
        for d in ("pending", "inflight", "dead"):
            (self.base / d).mkdir(parents=True, exist_ok=True)

    def send(self, job: ClaimJob) -> None:
        name = f"{time.time_ns()}-{safe_id(job.claim_id, 'claim')}.json"
        _atomic_write(self.base / "pending" / name, job.model_dump_json().encode())

    def _requeue_expired(self) -> None:
        now = time.time()
        for f in (self.base / "inflight").glob("*.json"):
            try:
                if now - f.stat().st_mtime > self.visibility_timeout_s:
                    os.replace(f, self.base / "pending" / f.name)
            except FileNotFoundError:
                continue

    def receive(self, max_messages: int = 1) -> list[ReceivedJob]:
        self._requeue_expired()
        out: list[ReceivedJob] = []
        for f in sorted((self.base / "pending").glob("*.json")):
            if len(out) >= max_messages:
                break
            target = self.base / "inflight" / f.name
            try:
                os.replace(f, target)  # atomic claim: loser gets FileNotFoundError
            except FileNotFoundError:
                continue
            job = ClaimJob.model_validate_json(target.read_text())
            out.append(ReceivedJob(job=job, receipt=f.name, delivery_count=job.attempt + 1))
        return out

    def complete(self, received: ReceivedJob) -> None:
        (self.base / "inflight" / received.receipt).unlink(missing_ok=True)

    def abandon(self, received: ReceivedJob) -> None:
        src = self.base / "inflight" / received.receipt
        if not src.exists():
            return
        job = received.job.model_copy(update={"attempt": received.job.attempt + 1})
        _atomic_write(self.base / "pending" / received.receipt, job.model_dump_json().encode())
        src.unlink(missing_ok=True)

    def dead_letter(self, received: ReceivedJob, reason: str) -> None:
        src = self.base / "inflight" / received.receipt
        payload = {"job": received.job.model_dump(), "reason": reason}
        _atomic_write(self.base / "dead" / received.receipt, json.dumps(payload).encode())
        src.unlink(missing_ok=True)

    def pending_count(self) -> int:
        return len(list((self.base / "pending").glob("*.json")))

    def dead_count(self) -> int:
        return len(list((self.base / "dead").glob("*.json")))


class LocalAuditLog:
    def __init__(self, root: Path) -> None:
        self.path = root / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: AuditEvent) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    def list_events(self, tenant_id: str, resource: str | None = None) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events = [
            AuditEvent.model_validate_json(line)
            for line in self.path.read_text().splitlines()
            if line
        ]
        return [
            e
            for e in events
            if e.tenant_id == tenant_id and (resource is None or e.resource == resource)
        ]
