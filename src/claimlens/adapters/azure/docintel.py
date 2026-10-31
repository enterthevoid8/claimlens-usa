"""Azure AI Document Intelligence (prebuilt-layout) as a LayoutAnalyzer."""

from __future__ import annotations

import io
from typing import Any

from claimlens.adapters.azure.credentials import credential
from claimlens.adapters.ports import LayoutResult


class DocIntelLayoutAnalyzer:
    def __init__(self, endpoint: str, client: Any | None = None) -> None:
        if client is None:
            from azure.ai.documentintelligence import DocumentIntelligenceClient

            client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential())
        self.client = client

    def analyze(self, data: bytes, content_type: str) -> LayoutResult:
        poller = self.client.begin_analyze_document(
            "prebuilt-layout",
            io.BytesIO(data),
            content_type="application/octet-stream",
            output_content_format="markdown",
        )
        result = poller.result()
        text = result.content or ""
        pages: list[str] = []
        for page in result.pages or []:
            spans = page.spans or []
            if spans:
                pages.append("".join(text[s.offset : s.offset + s.length] for s in spans))
        if not pages:
            pages = [text]
        tables = []
        for t in result.tables or []:
            grid = [["" for _ in range(t.column_count)] for _ in range(t.row_count)]
            for cell in t.cells:
                grid[cell.row_index][cell.column_index] = cell.content or ""
            tables.append(grid)
        return LayoutResult(pages=pages, tables=tables)
