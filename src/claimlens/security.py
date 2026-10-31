"""Small security helpers shared by adapters, API and logging."""

from __future__ import annotations

import logging
import re

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_id(value: str, kind: str = "id") -> str:
    """Reject anything that could escape a path or partition key (``../``, slashes, spaces)."""
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {kind}")
    return value


# --- log redaction ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "[SSN]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)(?:\+?1)?[2-9]\d{2}[2-9]\d{6}(?!\d)"), "[PHONE]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs identifiers from log messages before any handler sees them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.getMessage()))
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            '{"t":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        )
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
