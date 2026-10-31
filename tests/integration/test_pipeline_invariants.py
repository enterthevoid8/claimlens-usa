from __future__ import annotations

from claimlens.domain.models import RuleStatus, Severity
from claimlens.ml.train_risk import analyse_case
from claimlens.synthetic.generator import SyntheticCase


def test_every_synthetic_case_analyses_cleanly(cases: list[SyntheticCase]) -> None:
    for case in cases:
        a = analyse_case(case)
        assert a.rules and len(a.rules) == 18
        assert a.suggested_route in {"review", "request_info"}
        assert all(r.message for r in a.rules)
        assert 0.0 <= a.extracted.extraction_confidence <= 1.0
        # a blocker-level failure can never coexist with an "all clear" summary
        if any(r.status == RuleStatus.FAIL and r.severity == Severity.BLOCKER for r in a.rules):
            assert "need attention" in a.summary


def test_missing_discharge_summary_is_never_a_clean_pass(cases: list[SyntheticCase]) -> None:
    for case in (c for c in cases if "discharge_summary.txt" not in c.documents):
        a = analyse_case(case)
        by_id = {r.rule_id: r for r in a.rules}
        assert by_id["R010"].status == RuleStatus.FAIL
        assert (
            by_id["R007"].status == RuleStatus.UNKNOWN
            and by_id["R014"].status == RuleStatus.UNKNOWN
        )
        assert a.suggested_route == "request_info"


def test_features_are_deterministic(cases: list[SyntheticCase]) -> None:
    assert analyse_case(cases[5]).features == analyse_case(cases[5]).features
