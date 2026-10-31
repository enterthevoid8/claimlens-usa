from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def precision_at_fraction(y: np.ndarray, score: np.ndarray, frac: float = 0.2) -> float:
    k = max(1, int(len(y) * frac))
    order = np.argsort(-score, kind="stable")[:k]
    return float(y[order].mean())


def summarise(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "n": float(len(y)),
        "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else float("nan"),
        "pr_auc": float(average_precision_score(y, p)) if y.sum() else float("nan"),
        "brier": float(brier_score_loss(y, p)),
        "ece": expected_calibration_error(y, p),
        "precision_at_20pct": precision_at_fraction(y, p, 0.2),
    }
