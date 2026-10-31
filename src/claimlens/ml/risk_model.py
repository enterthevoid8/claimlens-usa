"""Calibrated risk model: LightGBM + isotonic calibration, loaded from a hash-verified bundle.

Bundle layout (one directory per version)::

    model.txt            LightGBM native text format (no pickle)
    calibration.json     isotonic thresholds fitted on a held-out split
    anomaly.joblib       claim-level Isolation Forest (hash-verified before loading)
    hospital_stats.json  historical query rate per hospital
    manifest.json        version, feature names, metrics, gate result, sha256 of every file

Reasons are TreeSHAP contributions (LightGBM ``pred_contrib``) in log-odds of the uncalibrated model.
Isotonic calibration is monotone, so the *direction* of each reason carries over to the calibrated probability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from claimlens.domain.models import RiskBand, RiskReason, RiskScore
from claimlens.ml.anomaly import ClaimAnomalyModel
from claimlens.ml.features import FEATURE_NAMES, Features
from claimlens.ml.hospital_stats import HospitalStats

BAND_LOW, BAND_HIGH = 0.25, 0.60

_LABELS = {
    "n_fail_blocker": "policy checks that look like blockers",
    "n_fail_warn": "policy checks with warnings",
    "n_unknown": "checks that could not be verified",
    "missing_docs": "required documents missing",
    "price_z_mean": "items priced above peer hospitals",
    "price_z_max": "the most over-priced line item",
    "n_duplicates": "repeated billing lines",
    "n_unbundling": "global package billed together with its components",
    "n_days_over_stay": "days billed beyond the stay",
    "share_consumable": "share of the bill that is supplies",
    "share_room": "share of the bill that is room and ICU",
    "claim_anomaly_pct": "how unusual the whole bill is versus past claims",
    "hospital_hist_rate": "this hospital's history of denied or pended claims",
    "los_ratio": "length of stay relative to the typical stay",
    "filing_lag_ratio": "how close the claim is to the timely-filing deadline",
    "in_network": "provider is in the plan's network",
    "plan_requires_network": "plan only pays in-network (HMO or EPO)",
    "within_waiting": "service soon after coverage started",
    "policy_age_days_log": "how long coverage has been in force",
    "log_total": "size of the claim",
    "cost_per_day_log": "cost per day of stay",
    "extraction_confidence": "how completely the documents could be read",
    "n_injection_flags": "suspicious text in the documents",
    "coinsurance_pct": "plan coinsurance rate",
    "is_emergency": "emergency admission",
}


def describe(feature: str, value: float | None, direction: str) -> str:
    label = _LABELS.get(feature, feature.replace("_", " "))
    v = "not available" if value is None else f"{value:.2f}".rstrip("0").rstrip(".")
    verb = "raises" if direction == "increases" else "lowers"
    return f"{label[:1].upper() + label[1:]} (value {v}): this {verb} the estimated chance of a denial, pend or reduction."


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class BundleIntegrityError(RuntimeError):
    pass


def verify_bundle(directory: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if sha256_file(directory / name) != expected:
            raise BundleIntegrityError(f"{name} does not match the manifest hash")
    return manifest


@dataclass
class RiskModel:
    booster: lgb.Booster
    calib_x: np.ndarray
    calib_y: np.ndarray
    feature_names: list[str]
    version: str
    manifest: dict[str, Any]

    def _row(self, features: Features) -> np.ndarray:
        values: list[float] = []
        for n in self.feature_names:
            v = features.get(n)
            values.append(np.nan if v is None else float(v))
        return np.array([values])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = np.asarray(self.booster.predict(X))
        return np.asarray(np.interp(raw, self.calib_x, self.calib_y))

    def score(self, features: Features, top_k: int = 3) -> RiskScore:
        X = self._row(features)
        p = float(self.predict_proba(X)[0])
        contrib = np.asarray(self.booster.predict(X, pred_contrib=True))[0][:-1]
        order = np.argsort(-np.abs(contrib))
        reasons: list[RiskReason] = []
        for i in order:
            if len(reasons) >= top_k:
                break
            if abs(contrib[i]) < 0.05:
                break
            name = self.feature_names[i]
            direction = "increases" if contrib[i] > 0 else "decreases"
            reasons.append(
                RiskReason(
                    feature=name,
                    contribution=round(float(contrib[i]), 3),
                    direction=direction,
                    text=describe(name, features.get(name), direction),
                )
            )
        band = (
            RiskBand.LOW if p < BAND_LOW else RiskBand.HIGH if p >= BAND_HIGH else RiskBand.MEDIUM
        )
        return RiskScore(
            probability=round(p, 4), band=band, reasons=reasons, model_version=self.version
        )


@dataclass
class ModelBundle:
    risk: RiskModel
    anomaly: ClaimAnomalyModel | None
    hospital_stats: HospitalStats

    @classmethod
    def load(cls, directory: Path) -> ModelBundle:
        import joblib

        manifest = verify_bundle(directory)
        booster = lgb.Booster(model_file=str(directory / "model.txt"))
        cal = json.loads((directory / "calibration.json").read_text(encoding="utf-8"))
        risk = RiskModel(
            booster=booster,
            calib_x=np.array(cal["x"]),
            calib_y=np.array(cal["y"]),
            feature_names=manifest["feature_names"],
            version=manifest["version"],
            manifest=manifest,
        )
        if risk.feature_names != FEATURE_NAMES:
            raise BundleIntegrityError(
                "bundle was trained with a different feature set than this code"
            )
        anomaly = joblib.load(directory / "anomaly.joblib")
        stats = HospitalStats.load(directory / "hospital_stats.json")
        return cls(risk=risk, anomaly=anomaly, hospital_stats=stats)

    @classmethod
    def load_current(cls, model_dir: Path) -> ModelBundle | None:
        pointer = model_dir / "risk" / "CURRENT"
        if not pointer.exists():
            return None
        return cls.load(model_dir / "risk" / pointer.read_text().strip())
