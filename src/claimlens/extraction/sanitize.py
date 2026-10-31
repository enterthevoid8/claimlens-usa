"""Treat every uploaded document as untrusted data.

We cannot reliably *detect* prompt injection, so the real defences are structural (extraction has no
tools, outputs are schema-validated, rules and models ignore free text, and nothing here can approve
or deny a claim). This module adds cheap detection so reviewers are warned, plus text hygiene.
"""

from __future__ import annotations

import re
import unicodedata

MAX_TEXT_CHARS = 200_000

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿‪‫‬‭‮"))

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system)\b[^.\n]{0,30}\b(instruction|prompt|rule|guideline)s?",
            re.I,
        ),
    ),
    ("role_hijack", re.compile(r"\b(you are now|act as|pretend to be|from now on you)\b", re.I)),
    ("role_marker", re.compile(r"^\s*(system|assistant|developer)\s*:", re.I | re.M)),
    (
        "decision_steering",
        re.compile(
            r"\b(approve|accept|pass|clear)\b[^.\n]{0,25}\b(this|the)\b[^.\n]{0,15}\bclaim\b|\b(do not|don't|never)\b[^.\n]{0,20}\b(flag|reject|deny|pend|query|review)\b|\bmark\b[^.\n]{0,20}\bclaim\b[^.\n]{0,15}\b(valid|approved|genuine|clean)\b",
            re.I,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,25}\b(system prompt|your instructions|hidden prompt|api key|secret)\b",
            re.I,
        ),
    ),
    ("template_tokens", re.compile(r"<\|[a-z_]+\|>|\[/?INST\]|###\s*(instruction|system)", re.I)),
]


def clean_text(text: str) -> tuple[str, list[str]]:
    """Return (cleaned text, flags). Removes invisible characters; never executes anything."""
    flags: list[str] = []
    if any(ord(c) in _ZERO_WIDTH for c in text):
        flags.append("hidden_characters: zero-width or bidi control characters were removed")
    text = text.translate(_ZERO_WIDTH)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    if len(text) > MAX_TEXT_CHARS:
        flags.append(f"oversized_text: truncated from {len(text)} characters")
        text = text[:MAX_TEXT_CHARS]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for code, pattern in _PATTERNS:
            if pattern.search(line):
                snippet = re.sub(r"\s+", " ", line.strip())[:120]
                flags.append(f"{code}: line {lineno}: {snippet}")
                break
    return text, flags
