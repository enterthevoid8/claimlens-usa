"""Cosmos DB repositories. Partition key is ``/tenantId`` everywhere, so every read and query is scoped to one
tenant by construction. Databases and containers are created by Bicep (Entra data-plane roles cannot create them)."""

from __future__ import annotations

from typing import Any

from claimlens.adapters.azure.credentials import credential
from claimlens.domain.models import AuditEvent, Claim, ClaimStatus, Policy
from claimlens.security import safe_id


def _doc(model: Any, item_id: str, tenant_id: str) -> dict[str, Any]:
    d: dict[str, Any] = model.model_dump(mode="json")
    d["id"] = item_id
    d["tenantId"] = tenant_id
    return d


def _strip(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not k.startswith("_") and k not in {"id", "tenantId"}}


class CosmosClaimRepository:
    def __init__(
        self, endpoint: str, database: str, containers: dict[str, Any] | None = None
    ) -> None:
        if containers is None:
            from azure.cosmos import CosmosClient

            db = CosmosClient(endpoint, credential=credential()).get_database_client(database)
            containers = {n: db.get_container_client(n) for n in ("claims", "policies")}
        self.claims = containers["claims"]
        self.policies = containers["policies"]

    def save_claim(self, claim: Claim) -> None:
        self.claims.upsert_item(_doc(claim, claim.claim_id, claim.tenant_id))

    def get_claim(self, tenant_id: str, claim_id: str) -> Claim | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            item = self.claims.read_item(item=safe_id(claim_id), partition_key=safe_id(tenant_id))
        except CosmosResourceNotFoundError:
            return None
        return Claim.model_validate(_strip(item))

    def list_claims(
        self, tenant_id: str, status: ClaimStatus | None = None, submitted_by: str | None = None
    ) -> list[Claim]:
        query = "SELECT * FROM c WHERE c.tenantId = @t"
        params: list[dict[str, Any]] = [{"name": "@t", "value": safe_id(tenant_id)}]
        if status:
            query += " AND c.status = @s"
            params.append({"name": "@s", "value": status.value})
        if submitted_by:
            query += " AND c.submitted_by = @u"
            params.append({"name": "@u", "value": submitted_by})
        items = self.claims.query_items(query=query, parameters=params, partition_key=tenant_id)
        return sorted((Claim.model_validate(_strip(i)) for i in items), key=lambda c: c.created_at)

    def delete_claim(self, tenant_id: str, claim_id: str) -> bool:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self.claims.delete_item(item=safe_id(claim_id), partition_key=safe_id(tenant_id))
        except CosmosResourceNotFoundError:
            return False
        return True

    def save_policy(self, policy: Policy) -> None:
        self.policies.upsert_item(_doc(policy, policy.policy_id, policy.tenant_id))

    def get_policy(self, tenant_id: str, policy_id: str) -> Policy | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            item = self.policies.read_item(
                item=safe_id(policy_id), partition_key=safe_id(tenant_id)
            )
        except CosmosResourceNotFoundError:
            return None
        return Policy.model_validate(_strip(item))


class CosmosAuditLog:
    def __init__(self, endpoint: str, database: str, container: Any | None = None) -> None:
        if container is None:
            from azure.cosmos import CosmosClient

            container = (
                CosmosClient(endpoint, credential=credential())
                .get_database_client(database)
                .get_container_client("audit")
            )
        self.container = container

    def append(self, event: AuditEvent) -> None:
        self.container.create_item(
            _doc(event, event.event_id, event.tenant_id)
        )  # create, never upsert: append-only

    def list_events(self, tenant_id: str, resource: str | None = None) -> list[AuditEvent]:
        query = "SELECT * FROM c WHERE c.tenantId = @t"
        params: list[dict[str, Any]] = [{"name": "@t", "value": safe_id(tenant_id)}]
        if resource:
            query += " AND c.resource = @r"
            params.append({"name": "@r", "value": resource})
        return [
            AuditEvent.model_validate(_strip(i))
            for i in self.container.query_items(
                query=query, parameters=params, partition_key=tenant_id
            )
        ]
