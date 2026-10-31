"""Local hybrid retrieval: idf-weighted keyword coverage + hashed-vector cosine.

``score`` is an *absolute* relevance signal (0..1), 70% keyword coverage: the share of the question's informative words
that the clause contains. It is what lets the explainer say "not in your policy" instead of returning
the least-bad chunk. The Azure adapter (``adapters/azure/search.py``) uses AI Search hybrid retrieval
and maps its reranker score onto the same ``ScoredChunk`` shape.
"""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from claimlens.adapters.ports import IndexedChunk, ScoredChunk

_STOP = set(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "am",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "i",
        "my",
        "me",
        "we",
        "our",
        "you",
        "your",
        "as",
        "about",
        "into",
        "any",
        "all",
        "what",
        "which",
        "who",
        "how",
        "when",
        "why",
        "there",
        "their",
        "they",
        "them",
        "he",
        "she",
        "his",
        "her",
        "not",
        "no",
        "happen",
        "happens",
        "go",
        "get",
        "have",
        "has",
        "had",
        "long",
        "much",
        "many",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")
_SYN = {
    "covered": "cover",
    "covers": "cover",
    "coverage": "cover",
    "paid": "pay",
    "payable": "pay",
    "pays": "pay",
    "payment": "pay",
    "file": "filing",
    "filed": "filing",
    "files": "filing",
    "deadline": "limit",
    "hospital": "provider",
    "hospitals": "provider",
    "facility": "provider",
    "facilities": "provider",
    "doctor": "provider",
    "denied": "deni",
    "denial": "deni",
    "denials": "deni",
    "deny": "deni",
    "denies": "deni",
}


def _stem(w: str) -> str:
    if w in _SYN:
        return _SYN[w]
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


_PREFIX = re.compile(r"\b(pre|non|post)[-\s](?=[a-z])")
_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), r)
    for p, r in [
        (r"\bco[-\s]?pay(?:ment|s)?\b", "co payment"),
        (r"\bco[-\s]?insurance\b", "coinsurance"),
        (r"\bout[-\s]of[-\s]network\b|\boon\b", "outofnetwork"),
        (r"\bin[-\s]network\b", "innetwork"),
        (
            r"\bprior[-\s]auth(?:orization|orisation)?s?\b|\bpre[-\s]?auth(?:orization|orisation)?s?\b|\bpre[-\s]?cert(?:ification)?\b",
            "priorauth",
        ),
        (r"\bout[-\s]of[-\s]pocket\b|\boop\b", "outofpocket"),
        (r"\bbalance[-\s]bill(?:ing|ed)?\b", "balancebill"),
        (r"\beob\b", "explanation benefits"),
    ]
]


def tokens(text: str) -> list[str]:
    text = text.lower()
    for pattern, repl in _ALIASES:
        text = pattern.sub(repl, text)
    text = _PREFIX.sub(r"\1", text)
    return [_stem(w) for w in _TOKEN.findall(text) if w not in _STOP]


_VEC = HashingVectorizer(
    n_features=2**13, alternate_sign=False, norm="l2", analyzer=lambda s: tokens(s)
)


class LocalPolicyIndex:
    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str], list[IndexedChunk]] = {}
        self._tok: dict[str, set[str]] = {}
        self._vec: dict[tuple[str, str], np.ndarray] = {}

    def index(self, chunks: list[IndexedChunk]) -> None:
        by_policy: dict[tuple[str, str], list[IndexedChunk]] = {}
        for c in chunks:
            by_policy.setdefault((c.tenant_id, c.policy_id), []).append(c)
        for key, cs in by_policy.items():
            self._chunks[key] = cs
            for c in cs:
                self._tok[c.chunk_id] = set(tokens(c.text))
            self._vec[key] = _VEC.transform([c.text for c in cs]).toarray()

    def delete_policy(self, tenant_id: str, policy_id: str) -> None:
        for c in self._chunks.pop((tenant_id, policy_id), []):
            self._tok.pop(c.chunk_id, None)
        self._vec.pop((tenant_id, policy_id), None)

    def has_policy(self, tenant_id: str, policy_id: str) -> bool:
        return (tenant_id, policy_id) in self._chunks

    def search(self, tenant_id: str, policy_id: str, query: str, k: int = 4) -> list[ScoredChunk]:
        key = (tenant_id, policy_id)  # tenant is part of the key: no cross-tenant retrieval
        chunks = self._chunks.get(key)
        if not chunks:
            return []
        q = [t for t in set(tokens(query)) if len(t) > 1]
        if not q:
            return []
        n = len(chunks)
        df = Counter(t for c in chunks for t in self._tok[c.chunk_id])
        idf = {t: math.log(1 + (n + 1) / (df.get(t, 0) + 0.5)) for t in q}
        total = sum(idf.values())
        qv = _VEC.transform([query]).toarray()[0]
        sims = self._vec[key] @ qv
        scored: list[ScoredChunk] = []
        for i, c in enumerate(chunks):
            cov = sum(idf[t] for t in q if t in self._tok[c.chunk_id]) / total
            scored.append(ScoredChunk(chunk=c, score=round(0.7 * cov + 0.3 * float(sims[i]), 4)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]
