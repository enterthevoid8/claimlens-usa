"""Peer price book: expected unit price per item, with a metro multiplier and a log-space spread.

The shipped book is derived from the synthetic catalog (``scripts/build_price_book.py``). In production it
would be rebuilt from a payer's own historical paid claims or a licensed benchmark; the file format is the same.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from claimlens.domain.models import LineItem


@dataclass
class PriceCheck:
    item: LineItem
    key: str
    expected: float
    z: float
    ratio: float


class PriceBook:
    def __init__(self, data: dict[str, Any]) -> None:
        self.sigma: float = float(data["sigma"])
        self.city_multiplier: dict[str, float] = {
            k.lower(): v for k, v in data["city_multiplier"].items()
        }
        self.items: dict[str, dict[str, Any]] = data["items"]
        self.proc_aliases: dict[str, str] = {k.lower(): v for k, v in data["proc_aliases"].items()}
        self.version: str = data.get("version", "unversioned")
        self._phrases = sorted(
            ((p.lower(), k) for k, spec in data["matchers"].items() for p in spec["phrases"]),
            key=lambda t: len(t[0]),
            reverse=True,
        )
        self._linked = {k: spec for k, spec in data["matchers"].items() if spec.get("proc_linked")}

    def match(self, description: str, procedure: str | None = None) -> str | None:
        d = description.lower()
        for phrase, matcher_key in self._phrases:
            if phrase in d:
                if matcher_key in self._linked:
                    proc_key = self.proc_aliases.get((procedure or "").lower())
                    key = f"{matcher_key}|{proc_key}" if proc_key else None
                else:
                    key = matcher_key
                return key if key in self.items else None
        return None

    def check(self, item: LineItem, procedure: str | None, city: str | None) -> PriceCheck | None:
        key = self.match(item.description, procedure)
        if key is None:
            return None
        unit = (
            item.unit_price
            if item.unit_price
            else (item.amount / item.quantity if item.quantity else item.amount)
        )
        if unit <= 0:
            return None
        mult = self.city_multiplier.get((city or "").lower(), 1.0)
        expected = float(self.items[key]["median"]) * mult
        z = math.log(unit / expected) / self.sigma
        return PriceCheck(item=item, key=key, expected=expected, z=z, ratio=unit / expected)


@lru_cache
def default_price_book() -> PriceBook:
    text = (resources.files("claimlens.ml") / "reference" / "price_book.json").read_text(
        encoding="utf-8"
    )
    return PriceBook(json.loads(text))


def load_price_book(path: Path) -> PriceBook:
    return PriceBook(json.loads(path.read_text(encoding="utf-8")))
