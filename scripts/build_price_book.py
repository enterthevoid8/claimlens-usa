"""Rebuild src/claimlens/ml/reference/price_book.json from the synthetic catalog."""

from __future__ import annotations

import json
from pathlib import Path

from claimlens.synthetic import catalog as c

OUT = Path(__file__).resolve().parents[1] / "src/claimlens/ml/reference/price_book.json"


def build() -> dict:
    items: dict[str, dict] = {}
    matchers: dict[str, dict] = {}
    for key, (label, base) in c.ROOMS.items():
        items[key] = {"median": base, "category": "room"}
        matchers[key] = {"phrases": [label.split(" - ")[1].lower()]}
    # "private" alone must not capture "semi private"; matcher ordering is by phrase length
    for key, (names, base, cat) in c.GENERIC_ITEMS.items():
        items[key] = {"median": base, "category": cat}
        matchers[key] = {"phrases": [n.lower() for n in names]}
    proc_aliases: dict[str, str] = {}
    for p in c.PROCEDURES:
        if p.kind == "medical":
            continue
        proc_aliases[p.procedure] = p.key
        for suffix, (_label, share, cat) in c.PROC_ITEMS.items():
            items[f"{suffix}|{p.key}"] = {"median": round(p.base * share, 2), "category": cat}
    for suffix, (label, _, _) in c.PROC_ITEMS.items():
        matchers[suffix] = {"phrases": [label.lower()], "proc_linked": True}
    er = next(p for p in c.PROCEDURES if p.er_fee)
    items["er_fee"] = {"median": er.base, "category": "doctor_fee"}
    matchers["er_fee"] = {"phrases": ["emergency department visit"]}
    return {
        "version": "synthetic-us-1",
        "sigma": 0.2,
        "city_multiplier": c.CITY_MULTIPLIER,
        "items": items,
        "matchers": matchers,
        "proc_aliases": proc_aliases,
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
