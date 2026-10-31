"""Azure AI Search policy-clause index (hybrid keyword + vector, optional semantic reranker)."""

from __future__ import annotations

from typing import Any, Protocol

from claimlens.adapters.azure.credentials import credential
from claimlens.adapters.ports import IndexedChunk, ScoredChunk
from claimlens.security import safe_id

VECTOR_DIMS = 1536


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def ensure_index(endpoint: str, name: str, dims: int = VECTOR_DIMS) -> None:
    """Create (or update) the index. Run once from deployment tooling, not on the request path."""
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SimpleField(name="tenantId", type="Edm.String", filterable=True),
        SimpleField(name="policyId", type="Edm.String", filterable=True),
        SimpleField(name="clause", type="Edm.String", filterable=True),
        SearchableField(name="title", type="Edm.String"),
        SearchableField(name="text", type="Edm.String"),
        SearchField(
            name="vector",
            type="Collection(Edm.Single)",
            searchable=True,
            vector_search_dimensions=dims,
            vector_search_profile_name="hnsw",
        ),
    ]
    index = SearchIndex(
        name=name,
        fields=fields,
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-cfg")],
            profiles=[VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw-cfg")],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="default",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[SemanticField(field_name="text")],
                    ),
                )
            ]
        ),
    )
    SearchIndexClient(endpoint, credential()).create_or_update_index(index)


class AzureSearchPolicyIndex:
    def __init__(
        self,
        endpoint: str,
        index_name: str,
        embedder: Embedder | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from azure.search.documents import SearchClient

            client = SearchClient(endpoint, index_name, credential())
        self.client = client
        self.embedder = embedder

    @staticmethod
    def _filter(tenant_id: str, policy_id: str) -> str:
        return f"tenantId eq '{safe_id(tenant_id)}' and policyId eq '{safe_id(policy_id)}'"  # ids are validated: no quote injection

    def index(self, chunks: list[IndexedChunk]) -> None:
        vectors = (
            self.embedder.embed([c.text for c in chunks]) if self.embedder else [None] * len(chunks)
        )
        docs = []
        for c, v in zip(chunks, vectors, strict=True):
            d: dict[str, Any] = {
                "id": c.chunk_id.replace(":", "_").replace(".", "-"),
                "tenantId": c.tenant_id,
                "policyId": c.policy_id,
                "clause": c.clause,
                "title": c.title,
                "text": c.text,
            }
            if v is not None:
                d["vector"] = v
            docs.append(d)
        self.client.merge_or_upload_documents(documents=docs)

    def search(self, tenant_id: str, policy_id: str, query: str, k: int = 4) -> list[ScoredChunk]:
        kwargs: dict[str, Any] = {
            "search_text": query,
            "filter": self._filter(tenant_id, policy_id),
            "top": k,
            "query_type": "semantic",
            "semantic_configuration_name": "default",
        }
        if self.embedder:
            from azure.search.documents.models import VectorizedQuery

            kwargs["vector_queries"] = [
                VectorizedQuery(
                    vector=self.embedder.embed([query])[0], k_nearest_neighbors=k, fields="vector"
                )
            ]
        out: list[ScoredChunk] = []
        for r in self.client.search(**kwargs):
            reranker = r.get("@search.reranker_score")  # 0..4
            score = (
                float(reranker) / 4.0
                if reranker is not None
                else min(1.0, float(r["@search.score"]))
            )
            out.append(
                ScoredChunk(
                    chunk=IndexedChunk(
                        chunk_id=r["id"],
                        clause=r["clause"],
                        title=r["title"],
                        text=r["text"],
                        policy_id=policy_id,
                        tenant_id=tenant_id,
                    ),
                    score=score,
                )
            )
        return out

    def delete_policy(self, tenant_id: str, policy_id: str) -> None:
        ids = [
            r["id"]
            for r in self.client.search(
                search_text="*", filter=self._filter(tenant_id, policy_id), select=["id"], top=1000
            )
        ]
        if ids:
            self.client.delete_documents(documents=[{"id": i} for i in ids])

    def has_policy(self, tenant_id: str, policy_id: str) -> bool:
        return any(
            True
            for _ in self.client.search(
                search_text="*", filter=self._filter(tenant_id, policy_id), select=["id"], top=1
            )
        )
