"""Train, calibrate, evaluate, gate and package the risk model (synthetic data only).

    claimlens train --n 5000 --seed 42

Writes ``models/risk/<version>/`` and, only if the release gate passes, points ``models/risk/CURRENT`` at it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import random
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression

from claimlens.analysis import Models, analyse_claim
from claimlens.domain.models import ClaimAnalysis, DocumentRef, RuleStatus, Severity
from claimlens.extraction.classify import classify_document
from claimlens.extraction.extract import DocText
from claimlens.extraction.local_extractor import RuleBasedExtractor
from claimlens.ml.anomaly import CLAIM_FEATURES, ClaimAnomalyModel
from claimlens.ml.features import FEATURE_NAMES, MONOTONE_UP
from claimlens.ml.hospital_stats import HospitalStats
from claimlens.ml.metrics import precision_at_fraction, summarise
from claimlens.ml.model_gate import evaluate_gate
from claimlens.ml.risk_model import sha256_file
from claimlens.synthetic.generator import REF_TODAY, SyntheticCase, generate_dataset

log = logging.getLogger(__name__)

LGB_PARAMS: dict[str, Any] = {
    "n_estimators": 600,
    "learning_rate": 0.04,
    "num_leaves": 15,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 2.0,
    "verbose": -1,
}


def case_inputs(case: SyntheticCase) -> tuple[list[DocText], list[DocumentRef]]:
    """Classify documents the same way production does (from content), not from file names."""
    docs, refs = [], []
    for name, text in case.documents.items():
        dt = classify_document(text, "")
        ref = DocumentRef(
            filename=name,
            content_type="text/plain",
            blob_path=name,
            sha256="0",
            size_bytes=len(text),
            doc_type=dt,
        )
        refs.append(ref)
        docs.append(DocText(document_id=ref.document_id, doc_type=dt, text=text))
    return docs, refs


def analyse_case(case: SyntheticCase, models: Models | None = None) -> ClaimAnalysis:
    docs, refs = case_inputs(case)
    return analyse_claim(
        claim_id=case.case_id,
        policy=case.policy,
        docs=docs,
        refs=refs,
        extractor=RuleBasedExtractor(),
        models=models,
        today=date.fromisoformat(case.meta.get("as_of", REF_TODAY.isoformat())),
    )


@dataclass
class Dataset:
    cases: list[SyntheticCase]
    analyses: list[ClaimAnalysis]

    def X(self, idx: np.ndarray) -> np.ndarray:
        return np.array(
            [
                [
                    np.nan
                    if self.analyses[i].features.get(n) is None
                    else float(self.analyses[i].features[n])
                    for n in FEATURE_NAMES
                ]
                for i in idx
            ]
        )

    def y(self, idx: np.ndarray) -> np.ndarray:
        return np.array([self.cases[i].label for i in idx])


def build_dataset(n: int, seed: int) -> Dataset:
    cases = generate_dataset(n, seed=seed)
    return Dataset(cases, [analyse_case(c) for c in cases])


def rules_only_score(a: ClaimAnalysis) -> float:
    s = 0.0
    for r in a.rules:
        if r.status == RuleStatus.FAIL:
            s += (
                2.0
                if r.severity == Severity.BLOCKER
                else 1.0
                if r.severity == Severity.WARN
                else 0.0
            )
    return s


def train(
    n: int = 5000, seed: int = 42, model_dir: Path = Path("models"), promote: bool = True
) -> dict[str, Any]:
    ds = build_dataset(n, seed)
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)

    def cut(a: float, b: float) -> np.ndarray:
        return np.asarray(order[int(n * a) : int(n * b)])

    tr, va, ca, te = cut(0, 0.60), cut(0.60, 0.70), cut(0.70, 0.85), cut(0.85, 1.0)

    # --- features that depend on the training split (no label leakage into val/cal/test)
    cl_rows = [
        i
        for i in tr
        if all(
            ds.analyses[i].features.get(k) is not None
            for k in CLAIM_FEATURES
            if k != "price_z_mean"
        )
    ]
    Xa = np.array(
        [
            [
                ds.analyses[i].features[k] if ds.analyses[i].features.get(k) is not None else 0.0
                for k in CLAIM_FEATURES
            ]
            for i in cl_rows
        ],
        dtype=float,
    )
    anomaly = ClaimAnomalyModel.fit(Xa, seed=seed)
    stats = HospitalStats.from_labels(
        [
            (ds.analyses[i].extracted.bill.hospital_name or "", ds.cases[i].label)
            for i in tr
            if ds.analyses[i].extracted.bill
        ]
    )
    train_set = {int(i) for i in tr}
    for i, a in enumerate(ds.analyses):
        f = a.features
        if all(f.get(k) is not None for k in CLAIM_FEATURES):
            f["claim_anomaly_pct"] = anomaly.percentile(
                np.array([f[k] for k in CLAIM_FEATURES], dtype=float)
            )
        bill = a.extracted.bill
        if bill and bill.hospital_name:
            rate, logn = stats.lookup(
                bill.hospital_name, exclude_label=ds.cases[i].label if i in train_set else None
            )
            f["hospital_hist_rate"], f["hospital_hist_log_n"] = rate, logn

    Xtr, ytr, Xva, yva, Xca, yca, Xte, yte = (
        ds.X(tr),
        ds.y(tr),
        ds.X(va),
        ds.y(va),
        ds.X(ca),
        ds.y(ca),
        ds.X(te),
        ds.y(te),
    )
    mono = [1 if f in MONOTONE_UP else 0 for f in FEATURE_NAMES]
    clf = lgb.LGBMClassifier(**LGB_PARAMS, monotone_constraints=mono, random_state=seed)
    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore"
        )  # eval_set is deprecated in the newest LightGBM but required by older ones
        clf.fit(
            Xtr,
            ytr,
            eval_set=[(Xva, yva)],
            eval_metric="binary_logloss",
            callbacks=[lgb.early_stopping(40, verbose=False)],
        )
    booster = clf.booster_
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(
        booster.predict(Xca), yca
    )
    p_te = np.interp(booster.predict(Xte), iso.X_thresholds_, iso.y_thresholds_)

    overall = summarise(yte, p_te)
    base_scores = np.array([rules_only_score(ds.analyses[i]) for i in te])
    base = summarise(yte, np.clip(base_scores / max(base_scores.max(), 1), 0, 1))
    base["precision_at_20pct"] = precision_at_fraction(yte, base_scores, 0.2)
    subgroups: dict[str, dict[str, float]] = {}
    for key in ("product", "market_tier"):
        for val in sorted({str(ds.cases[i].meta[key]) for i in te}):
            m = np.array([str(ds.cases[i].meta[key]) == val for i in te])
            subgroups[f"{key}={val}"] = summarise(yte[m], p_te[m])
    gate = evaluate_gate(overall, base, subgroups)

    # --- package
    data_id = hashlib.sha256(f"{n}:{seed}:{FEATURE_NAMES}".encode()).hexdigest()[:8]
    tmp = model_dir / "risk" / f".building-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(tmp / "model.txt"))
    (tmp / "calibration.json").write_text(
        json.dumps({"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()})
    )
    joblib.dump(anomaly, tmp / "anomaly.joblib")
    (tmp / "hospital_stats.json").write_text(stats.to_json())
    version = f"risk-{sha256_file(tmp / 'model.txt')[:8]}-{data_id}"
    manifest = {
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "feature_names": FEATURE_NAMES,
        "synthetic_data": True,
        "n_cases": n,
        "seed": seed,
        "best_iteration": int(clf.best_iteration_ or 0),
        "params": {k: v for k, v in LGB_PARAMS.items()},
        "monotone_up": sorted(MONOTONE_UP),
        "metrics": {"overall": overall, "rules_only_baseline": base, "subgroups": subgroups},
        "gate": gate,
        "environment": {"python": platform.python_version(), "lightgbm": lgb.__version__},
        "files": {
            f: sha256_file(tmp / f)
            for f in ("model.txt", "calibration.json", "anomaly.joblib", "hospital_stats.json")
        },
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    final = model_dir / "risk" / version
    if final.exists():
        for p in final.iterdir():
            p.unlink()
        final.rmdir()
    tmp.rename(final)
    if gate["passed"] and promote:
        (model_dir / "risk" / "CURRENT").write_text(version)
    _maybe_log_mlflow(manifest, final)
    return manifest


def _maybe_log_mlflow(manifest: dict[str, Any], bundle: Path) -> None:
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return
    try:
        import mlflow
    except ImportError:
        log.warning("MLFLOW_TRACKING_URI is set but mlflow is not installed; skipping tracking")
        return
    with mlflow.start_run(run_name=manifest["version"]):
        mlflow.log_params(
            {k: v for k, v in manifest["params"].items()}
            | {"n_cases": manifest["n_cases"], "seed": manifest["seed"]}
        )
        for k, v in manifest["metrics"]["overall"].items():
            mlflow.log_metric(k, v)
        mlflow.log_metric("baseline_roc_auc", manifest["metrics"]["rules_only_baseline"]["roc_auc"])
        mlflow.set_tag("gate_passed", str(manifest["gate"]["passed"]))
        mlflow.log_artifacts(str(bundle))


if __name__ == "__main__":
    random.seed(0)
    m = train()
    print(json.dumps(m["metrics"]["overall"], indent=2))
    print("gate passed:", m["gate"]["passed"])
