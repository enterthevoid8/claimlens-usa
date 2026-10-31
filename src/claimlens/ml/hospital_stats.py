"""Historical query rate per hospital, with shrinkage toward the portfolio rate.

In production this is refreshed from reviewer decisions; for training we build it from the training split
only, and use a leave-one-out value for each training row so a claim never sees its own label.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from claimlens.extraction.parsing import normalize_name

SHRINKAGE_M = 20.0


class HospitalStats:
    def __init__(self, counts: dict[str, tuple[int, int]], prior: float) -> None:
        self.counts = counts  # normalized name -> (positives, total)
        self.prior = prior

    @classmethod
    def from_labels(cls, pairs: list[tuple[str, int]]) -> HospitalStats:
        counts: dict[str, list[int]] = {}
        for name, y in pairs:
            c = counts.setdefault(normalize_name(name), [0, 0])
            c[0] += y
            c[1] += 1
        total = sum(c[1] for c in counts.values())
        prior = sum(c[0] for c in counts.values()) / total if total else 0.3
        return cls({k: (v[0], v[1]) for k, v in counts.items()}, prior)

    def lookup(self, name: str | None, exclude_label: int | None = None) -> tuple[float, float]:
        """(shrunk rate, log1p(n)). ``exclude_label`` removes one known claim (leave-one-out)."""
        pos, n = self.counts.get(normalize_name(name), (0, 0))
        if exclude_label is not None and n > 0:
            pos, n = pos - exclude_label, n - 1
        rate = (pos + self.prior * SHRINKAGE_M) / (n + SHRINKAGE_M)
        return rate, math.log1p(n)

    def to_json(self) -> str:
        return json.dumps({"prior": self.prior, "counts": self.counts})

    @classmethod
    def from_json(cls, text: str) -> HospitalStats:
        d = json.loads(text)
        return cls({k: (v[0], v[1]) for k, v in d["counts"].items()}, d["prior"])

    @classmethod
    def load(cls, path: Path) -> HospitalStats:
        return cls.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def empty(cls) -> HospitalStats:
        return cls({}, 0.3)
