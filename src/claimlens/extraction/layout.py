"""Layout analysis.

``LocalLayoutAnalyzer`` handles text and text-layer PDFs. Scans and photos need OCR, which in this
project means Azure Document Intelligence (see ``adapters/azure/docintel.py``); locally we fail loudly
rather than pretend.
"""

from __future__ import annotations

import io

from claimlens.adapters.ports import LayoutResult

TEXT_TYPES = {"text/plain", "text/markdown"}
PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff"}
ALLOWED_TYPES = TEXT_TYPES | PDF_TYPES | IMAGE_TYPES


class UnsupportedDocument(ValueError):
    pass


def sniff_content_type(data: bytes, declared: str) -> str:
    """Trust magic bytes over the client-declared type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if declared in TEXT_TYPES:
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        return declared
    return "application/octet-stream"


class LocalLayoutAnalyzer:
    def analyze(self, data: bytes, content_type: str) -> LayoutResult:
        if content_type in TEXT_TYPES:
            return LayoutResult(pages=[data.decode("utf-8", errors="replace")])
        if content_type in PDF_TYPES:
            try:
                from pypdf import PdfReader
            except ImportError as exc:  # pragma: no cover
                raise UnsupportedDocument("PDF support needs the 'pdf' extra (pypdf)") from exc
            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
            if not any(p.strip() for p in pages):
                raise UnsupportedDocument(
                    "PDF has no text layer; OCR needs Azure Document Intelligence"
                )
            return LayoutResult(pages=pages)
        raise UnsupportedDocument(f"{content_type} needs OCR (Azure Document Intelligence)")
