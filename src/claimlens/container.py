"""Dependency wiring. One place decides local vs. Azure; everything else sees ports."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claimlens.adapters.ports import (
    AuditLog,
    BlobStore,
    ClaimRepository,
    JobQueue,
    LayoutAnalyzer,
    PolicyIndex,
    StructuredExtractor,
    TextGenerator,
)
from claimlens.analysis import Models
from claimlens.extraction.layout import LocalLayoutAnalyzer
from claimlens.extraction.local_extractor import RuleBasedExtractor
from claimlens.ml.price_book import default_price_book
from claimlens.ml.risk_model import ModelBundle
from claimlens.rag.index import LocalPolicyIndex
from claimlens.settings import Settings

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    blobs: BlobStore
    repo: ClaimRepository
    queue: JobQueue
    audit: AuditLog
    layout: LayoutAnalyzer
    extractor: StructuredExtractor
    index: PolicyIndex
    models: Models = field(default_factory=Models)
    generator: TextGenerator | None = None


def load_models(settings: Settings, model_store: Any | None = None) -> Models:
    model_dir: Path = settings.model_dir
    if settings.backend == "azure" and model_store is not None and settings.model_blob_prefix:
        model_dir = settings.data_dir / "models"
        version = settings.model_blob_prefix.rstrip("/").rsplit("/", 1)[-1]
        model_store.download_prefix(settings.model_blob_prefix, model_dir / "risk" / version)
        (model_dir / "risk" / "CURRENT").write_text(version)
    try:
        bundle = ModelBundle.load_current(model_dir)
    except Exception:
        log.exception("could not load the risk model bundle; continuing without risk scores")
        bundle = None
    if bundle is None:
        log.warning(
            "no risk model found in %s: claims will be analysed without a risk score", model_dir
        )
        return Models(price_book=default_price_book())
    return Models(
        risk=bundle.risk,
        anomaly=bundle.anomaly,
        hospital_stats=bundle.hospital_stats,
        price_book=default_price_book(),
    )


def build_container(settings: Settings) -> Container:
    if settings.backend == "local":
        from claimlens.adapters.local import (
            LocalAuditLog,
            LocalBlobStore,
            LocalClaimRepository,
            LocalJobQueue,
        )

        root = settings.data_dir
        return Container(
            settings=settings,
            blobs=LocalBlobStore(root),
            repo=LocalClaimRepository(root),
            queue=LocalJobQueue(root),
            audit=LocalAuditLog(root),
            layout=LocalLayoutAnalyzer(),
            extractor=RuleBasedExtractor(),
            index=LocalPolicyIndex(),
            models=load_models(settings),
        )

    from claimlens.adapters.azure.blob import AzureBlobStore
    from claimlens.adapters.azure.cosmos import CosmosAuditLog, CosmosClaimRepository
    from claimlens.adapters.azure.docintel import DocIntelLayoutAnalyzer
    from claimlens.adapters.azure.observability import configure_azure_monitor
    from claimlens.adapters.azure.openai_llm import (
        OpenAIEmbedder,
        OpenAIExtractor,
        OpenAITextGenerator,
    )
    from claimlens.adapters.azure.search import AzureSearchPolicyIndex
    from claimlens.adapters.azure.servicebus import ServiceBusJobQueue

    configure_azure_monitor(settings.appinsights_connection_string)
    blobs = AzureBlobStore(settings.storage_account_url, settings.blob_container)
    extractor: StructuredExtractor = RuleBasedExtractor()
    generator: TextGenerator | None = None
    embedder = None
    if settings.openai_endpoint:
        if settings.use_llm_extraction and settings.openai_deployment:
            extractor = OpenAIExtractor(settings.openai_endpoint, settings.openai_deployment)
        if settings.use_llm_explanations and settings.openai_deployment:
            generator = OpenAITextGenerator(settings.openai_endpoint, settings.openai_deployment)
        if settings.openai_embedding_deployment:
            embedder = OpenAIEmbedder(
                settings.openai_endpoint, settings.openai_embedding_deployment
            )
    return Container(
        settings=settings,
        blobs=blobs,
        repo=CosmosClaimRepository(settings.cosmos_endpoint, settings.cosmos_database),
        queue=ServiceBusJobQueue(settings.servicebus_namespace, settings.servicebus_queue),
        audit=CosmosAuditLog(settings.cosmos_endpoint, settings.cosmos_database),
        layout=DocIntelLayoutAnalyzer(settings.docintel_endpoint),
        extractor=extractor,
        index=AzureSearchPolicyIndex(
            settings.search_endpoint, settings.search_index, embedder=embedder
        ),
        models=load_models(
            settings, AzureBlobStore(settings.storage_account_url, settings.model_container)
        ),
        generator=generator,
    )
