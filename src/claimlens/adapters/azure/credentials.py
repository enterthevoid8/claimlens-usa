from __future__ import annotations

from functools import lru_cache
from typing import Any

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@lru_cache
def credential() -> Any:
    """Managed identity in Azure, developer login (az login / VS Code) on a laptop. No keys or secrets."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)
