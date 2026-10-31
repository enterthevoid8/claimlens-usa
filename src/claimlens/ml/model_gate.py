"""Release gate: a model only becomes CURRENT if every check passes. Thresholds are starting points."""

from __future__ import annotations

from typing import Any

GATE = {
    "min_roc_auc": 0.75,
    "max_brier": 0.20,
    "max_ece": 0.06,
    "min_auc_gain_over_rules": 0.02,
    "min_subgroup_auc": 0.68,
    "max_subgroup_auc_gap": 0.08,
    "min_subgroup_n": 80,
}


def evaluate_gate(
    overall: dict[str, float], baseline: dict[str, float], subgroups: dict[str, dict[str, float]]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    add(
        "roc_auc",
        overall["roc_auc"] >= GATE["min_roc_auc"],
        f"{overall['roc_auc']:.3f} >= {GATE['min_roc_auc']}",
    )
    add(
        "brier",
        overall["brier"] <= GATE["max_brier"],
        f"{overall['brier']:.3f} <= {GATE['max_brier']}",
    )
    add(
        "calibration_ece",
        overall["ece"] <= GATE["max_ece"],
        f"{overall['ece']:.3f} <= {GATE['max_ece']}",
    )
    gain = overall["roc_auc"] - baseline["roc_auc"]
    add(
        "beats_rules_only",
        gain >= GATE["min_auc_gain_over_rules"],
        f"AUC gain {gain:+.3f} over the rules-only baseline (need {GATE['min_auc_gain_over_rules']})",
    )
    for name, m in subgroups.items():
        if m["n"] < GATE["min_subgroup_n"] or m["roc_auc"] != m["roc_auc"]:
            add(
                f"subgroup:{name}",
                True,
                f"skipped (n={int(m['n'])} below {GATE['min_subgroup_n']})",
            )
            continue
        ok = (
            m["roc_auc"] >= GATE["min_subgroup_auc"]
            and (overall["roc_auc"] - m["roc_auc"]) <= GATE["max_subgroup_auc_gap"]
        )
        add(
            f"subgroup:{name}",
            ok,
            f"AUC {m['roc_auc']:.3f} (overall {overall['roc_auc']:.3f}, n={int(m['n'])})",
        )
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "thresholds": GATE}
