"""Runtime configuration. All values come from environment variables (prefix ``CLAIMLENS_``).

``BACKEND=local`` runs everything in-process with no cloud dependency; ``BACKEND=azure`` wires the
Azure adapters. Secrets are never read from settings: Azure access uses managed identity.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAIMLENS_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    backend: Literal["local", "azure"] = "local"
    data_dir: Path = Path(".claimlens")  # local backend: blobs, claims, models
    model_dir: Path = Path("models")

    # --- auth
    auth_mode: Literal["dev", "entra"] = "dev"
    dev_jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"  # noqa: S105
    entra_tenant_id: str = ""
    entra_audience: str = ""

    # --- limits
    max_upload_bytes: int = 10 * 1024 * 1024
    max_documents_per_claim: int = 12
    max_job_attempts: int = 3

    # --- Azure (only read when backend == azure)
    storage_account_url: str = ""
    blob_container: str = "claims"
    model_container: str = (
        "models"  # separate container: API and worker can read it but never write it
    )
    cosmos_endpoint: str = ""
    cosmos_database: str = "claimlens"
    servicebus_namespace: str = ""  # fully qualified, e.g. sb-xyz.servicebus.windows.net
    servicebus_queue: str = "claim-jobs"
    docintel_endpoint: str = ""
    openai_endpoint: str = ""
    openai_deployment: str = ""
    openai_embedding_deployment: str = ""
    search_endpoint: str = ""
    search_index: str = "policy-clauses"
    appinsights_connection_string: str = ""
    model_blob_prefix: str = (
        ""  # e.g. "risk/risk-abc123-def456": downloaded from the models container at startup
    )

    cors_origins: list[str] = []  # e.g. ["https://claimlens-web.azurestaticapps.net"]
    inline_processing: bool = False  # local demo: process in the API process instead of a worker

    # --- feature flags
    use_llm_extraction: bool = False  # azure backend: LLM structured extraction vs. rule parser
    use_llm_explanations: bool = False

    @model_validator(mode="after")
    def _prod_guards(self) -> Settings:
        if self.environment == "prod":
            if self.auth_mode == "dev":
                raise ValueError("auth_mode=dev is not allowed when environment=prod")
            if self.backend == "local":
                raise ValueError("backend=local is not allowed when environment=prod")
            if self.inline_processing:
                raise ValueError("inline_processing is for local demos only")
            if self.auth_mode == "entra" and not (self.entra_tenant_id and self.entra_audience):
                raise ValueError("entra_tenant_id and entra_audience are required for entra auth")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
