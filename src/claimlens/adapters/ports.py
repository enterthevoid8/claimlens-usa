"""Ports: the only interfaces the core package depends on.

Azure SDK calls live in ``adapters/azure``; filesystem equivalents live in ``adapters/local``.
Both implement these Protocols so the pipeline can be tested on a laptop with no cloud account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from claimlens.domain.models import (
    AuditEvent,
    Claim,
    ClaimJob,
    ClaimStatus,
    DischargeSummary,
    HospitalBill,
    Policy,
)


class BlobStore(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> None: ...
    def get(self, path: str) -> bytes: ...
    def delete_prefix(self, prefix: str) -> int: ...


class ClaimRepository(Protocol):
    def save_claim(self, claim: Claim) -> None: ...
    def get_claim(self, tenant_id: str, claim_id: str) -> Claim | None: ...
    def list_claims(
        self, tenant_id: str, status: ClaimStatus | None = None, submitted_by: str | None = None
    ) -> list[Claim]: ...
    def delete_claim(self, tenant_id: str, claim_id: str) -> bool: ...
    def save_policy(self, policy: Policy) -> None: ...
    def get_policy(self, tenant_id: str, policy_id: str) -> Policy | None: ...


@dataclass
class ReceivedJob:
    job: ClaimJob
    receipt: str = ""
    delivery_count: int = 1
    handle: Any = None  # transport-specific object (e.g. a Service Bus message), opaque to callers


class JobQueue(Protocol):
    def send(self, job: ClaimJob) -> None: ...
    def receive(self, max_messages: int = 1) -> list[ReceivedJob]: ...
    def complete(self, received: ReceivedJob) -> None: ...
    def abandon(self, received: ReceivedJob) -> None: ...
    def dead_letter(self, received: ReceivedJob, reason: str) -> None: ...


class AuditLog(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_events(self, tenant_id: str, resource: str | None = None) -> list[AuditEvent]: ...


@dataclass
class LayoutResult:
    pages: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # table -> row -> cell

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


class LayoutAnalyzer(Protocol):
    """Turns raw bytes (PDF, image, text) into text + tables."""

    def analyze(self, data: bytes, content_type: str) -> LayoutResult: ...


class StructuredExtractor(Protocol):
    """Turns untrusted document text into typed objects. Must not have tools or side effects."""

    name: str

    def extract_bill(self, text: str) -> HospitalBill: ...
    def extract_discharge(self, text: str) -> DischargeSummary: ...


@dataclass
class IndexedChunk:
    chunk_id: str
    clause: str
    title: str
    text: str
    policy_id: str
    tenant_id: str


@dataclass
class ScoredChunk:
    chunk: IndexedChunk
    score: float


class PolicyIndex(Protocol):
    def index(self, chunks: list[IndexedChunk]) -> None: ...
    def search(
        self, tenant_id: str, policy_id: str, query: str, k: int = 4
    ) -> list[ScoredChunk]: ...
    def delete_policy(self, tenant_id: str, policy_id: str) -> None: ...
    def has_policy(self, tenant_id: str, policy_id: str) -> bool: ...


class TextGenerator(Protocol):
    """Optional LLM used only to phrase grounded answers. Never makes decisions."""

    def generate(self, system: str, user: str) -> str: ...
