from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from claimlens.analysis import Models
from claimlens.ml.features import FEATURE_NAMES, MONOTONE_UP
from claimlens.ml.hospital_stats import HospitalStats
from claimlens.ml.model_gate import evaluate_gate
from claimlens.ml.price_book import default_price_book
from claimlens.ml.risk_model import BundleIntegrityError, ModelBundle
from claimlens.ml.train_risk import analyse_case, train
from claimlens.synthetic.generator import generate_dataset

OVERALL = {"roc_auc": 0.85, "brier": 0.15, "ece": 0.03, "n": 700.0}
BASE = {"roc_auc": 0.80}


def test_gate_passes_good_model() -> None:
    assert evaluate_gate(OVERALL, BASE, {"product=a": {"roc_auc": 0.84, "n": 300.0}})["passed"]


@pytest.mark.parametrize(
    ("overall", "base", "sub"),
    [
        ({**OVERALL, "roc_auc": 0.70}, {"roc_auc": 0.65}, {}),  # too weak
        ({**OVERALL, "brier": 0.30}, BASE, {}),  # badly calibrated
        ({**OVERALL, "ece": 0.12}, BASE, {}),
        (OVERALL, {"roc_auc": 0.84}, {}),  # does not beat the rules
        (OVERALL, BASE, {"product=weak": {"roc_auc": 0.70, "n": 300.0}}),  # one group left behind
    ],
)
def test_gate_blocks_bad_models(
    overall: dict[str, float], base: dict[str, float], sub: dict[str, dict[str, float]]
) -> None:
    assert not evaluate_gate(overall, base, sub)["passed"]


def test_gate_ignores_tiny_subgroups() -> None:
    assert evaluate_gate(OVERALL, BASE, {"product=tiny": {"roc_auc": 0.3, "n": 12.0}})["passed"]


def test_hospital_stats_leave_one_out_hides_own_label() -> None:
    stats = HospitalStats.from_labels(
        [("Sunrise Care Hospital", 1)] * 5 + [("Other Hospital", 0)] * 5
    )
    with_self, _ = stats.lookup("Sunrise Care Hospital")
    without_self, _ = stats.lookup("Sunrise Care Hospital", exclude_label=1)
    assert without_self < with_self
    unseen, logn = stats.lookup("Never Seen Hospital")
    assert unseen == pytest.approx(stats.prior) and logn == 0.0  # shrinks to the portfolio rate


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    model_dir = tmp_path_factory.mktemp("models")
    manifest = train(n=900, seed=3, model_dir=model_dir, promote=False)
    return model_dir / "risk" / manifest["version"]


@pytest.mark.slow
def test_bundle_loads_scores_and_explains(bundle_dir: Path) -> None:
    bundle = ModelBundle.load(bundle_dir)
    models = Models(
        risk=bundle.risk,
        anomaly=bundle.anomaly,
        hospital_stats=bundle.hospital_stats,
        price_book=default_price_book(),
    )
    for case in generate_dataset(25, seed=77):
        a = analyse_case(case, models)
        assert a.risk is not None and 0.0 < a.risk.probability < 1.0
        assert a.risk.model_version == bundle.risk.version
        assert len(a.risk.reasons) <= 3
        assert all(r.direction in {"increases", "decreases"} for r in a.risk.reasons)
        assert [r.contribution for r in a.risk.reasons] == sorted(
            (r.contribution for r in a.risk.reasons), key=abs, reverse=True
        )
        assert set(a.features) == set(FEATURE_NAMES)


@pytest.mark.slow
def test_manifest_records_what_a_reviewer_needs_to_audit(bundle_dir: Path) -> None:
    m = json.loads((bundle_dir / "manifest.json").read_text())
    assert m["synthetic_data"] is True and m["feature_names"] == FEATURE_NAMES
    assert {"overall", "rules_only_baseline", "subgroups"} <= set(m["metrics"])
    assert set(m["files"]) == {
        "model.txt",
        "calibration.json",
        "anomaly.joblib",
        "hospital_stats.json",
    }


@pytest.mark.slow
def test_tampered_bundle_is_refused(bundle_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(bundle_dir, copy)
    with (copy / "anomaly.joblib").open("ab") as fh:
        fh.write(b"\x00")
    with pytest.raises(BundleIntegrityError):
        ModelBundle.load(copy)


@pytest.mark.slow
def test_risk_never_decreases_when_a_monotone_feature_increases(bundle_dir: Path) -> None:
    risk = ModelBundle.load(bundle_dir).risk
    base = np.zeros((1, len(FEATURE_NAMES)))
    base[0, FEATURE_NAMES.index("log_total")] = 10.0
    base[0, FEATURE_NAMES.index("hospital_hist_rate")] = 0.3
    for name in sorted(MONOTONE_UP):
        j = FEATURE_NAMES.index(name)
        grid = (
            np.linspace(0.0, 1.0, 11) if name == "hospital_hist_rate" else np.linspace(0.0, 6.0, 13)
        )
        probs = []
        for v in grid:
            row = base.copy()
            row[0, j] = v
            probs.append(float(risk.predict_proba(row)[0]))
        assert all(b >= a - 1e-9 for a, b in itertools.pairwise(probs)), (
            f"{name} is not monotone: {probs}"
        )


@pytest.mark.slow
def test_missing_features_do_not_crash_scoring(bundle_dir: Path) -> None:
    risk = ModelBundle.load(bundle_dir).risk
    score = risk.score(dict.fromkeys(FEATURE_NAMES))
    assert 0.0 <= score.probability <= 1.0
