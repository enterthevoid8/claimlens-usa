from datetime import date

import pytest

from claimlens.domain.models import (
    DischargeSummary,
    DocumentRef,
    DocumentType,
    ExtractedClaimData,
    HospitalBill,
    ItemCategory,
    LineItem,
    RuleStatus,
    Severity,
)
from claimlens.rules.base import RuleContext, RuleEngine
from claimlens.rules.builtin import (
    AccidentLiability,
    Arithmetic,
    BenefitLimits,
    CodeFormats,
    CoveragePeriod,
    Dates,
    DocumentIntegrity,
    DocumentsComplete,
    EligibilityWaiting,
    Exclusions,
    LengthOfStay,
    MedicalNecessity,
    NetworkStatus,
    PatientIdentity,
    PriorAuth,
    TimelyFiling,
    default_rules,
)
from claimlens.rules.coding import make_npi
from claimlens.rules.policy_loader import instantiate_policy

TODAY = date(2025, 4, 1)  # 28 days after the sample discharge
NPI = make_npi("100300012")


def policy(product: str = "ppo_gold", **kw):  # type: ignore[no-untyped-def]
    p = instantiate_policy(
        product,
        policy_id="P1",
        tenant_id="t1",
        holder_name="Maria Garcia",
        start_date=date(2023, 1, 1),
        term_years=5,
        network_providers=["Lakeview Medical Center"],
    )
    return p.model_copy(update=kw)


def bill(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        bill_number="B1",
        hospital_name="Lakeview Medical Center",
        patient_name="Maria Garcia",
        provider_npi=NPI,
        state="IL",
        diagnosis_codes=["K35.80"],
        procedure_code="44970",
        admission_date=date(2025, 3, 1),
        discharge_date=date(2025, 3, 4),
        diagnosis="Acute appendicitis",
        procedure="Laparoscopic appendectomy",
        total_claimed=11_000.0,
        line_items=[
            LineItem(
                description="Room and board - Semi-private",
                category=ItemCategory.ROOM,
                quantity=3,
                unit_price=3000,
                amount=9000,
            ),
            LineItem(
                description="CBC",
                category=ItemCategory.DIAGNOSTIC,
                quantity=1,
                unit_price=2000,
                amount=2000,
            ),
        ],
    )
    return HospitalBill(**{**base, **kw})


def discharge(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        patient_name="Maria Garcia",
        diagnosis="Acute appendicitis",
        diagnosis_codes=["K35.80"],
        admission_date=date(2025, 3, 1),
        discharge_date=date(2025, 3, 4),
        is_emergency=True,
        is_accident=False,
        third_party_liability=None,
    )
    return DischargeSummary(**{**base, **kw})


def ctx(
    p=None,
    b="default",
    d="default",
    docs=(DocumentType.HOSPITAL_BILL, DocumentType.DISCHARGE_SUMMARY),
    **data_kw,
):  # type: ignore[no-untyped-def]
    data = ExtractedClaimData(
        bill=bill() if b == "default" else b,
        discharge=discharge() if d == "default" else d,
        **data_kw,
    )
    refs = [
        DocumentRef(
            filename=str(t),
            content_type="text/plain",
            blob_path="x",
            sha256="0",
            size_bytes=1,
            doc_type=t,
        )
        for t in docs
    ]
    return RuleContext(policy=p or policy(), data=data, documents=refs, today=TODAY)


def test_happy_path_has_no_failures() -> None:
    results = RuleEngine(default_rules()).run(ctx())
    assert [r.rule_id for r in results if r.status == RuleStatus.FAIL] == []


def test_coverage_period() -> None:
    assert CoveragePeriod().evaluate(ctx()).status == RuleStatus.PASS
    assert (
        CoveragePeriod().evaluate(ctx(b=bill(admission_date=date(2022, 1, 1)), d=None)).status
        == RuleStatus.FAIL
    )
    assert (
        CoveragePeriod().evaluate(ctx(b=bill(admission_date=None), d=None)).status
        == RuleStatus.UNKNOWN
    )


def test_eligibility_waiting_period() -> None:
    p = policy("hmo_silver", start_date=date(2025, 2, 20), waiting_period_days=60)
    r = EligibilityWaiting().evaluate(ctx(p=p))
    assert r.status == RuleStatus.FAIL and r.severity == Severity.BLOCKER
    assert EligibilityWaiting().evaluate(ctx(p=policy())).status == RuleStatus.PASS
    assert (
        EligibilityWaiting().evaluate(ctx(p=p, b=bill(admission_date=None), d=None)).status
        == RuleStatus.UNKNOWN
    )


def test_timely_filing() -> None:
    assert TimelyFiling().evaluate(ctx()).status == RuleStatus.PASS
    late = RuleContext(
        policy=policy("hdhp_bronze"),  # 90-day limit
        data=ctx().data,
        documents=ctx().documents,
        today=date(2025, 8, 1),
    )
    r = TimelyFiling().evaluate(late)
    assert r.status == RuleStatus.FAIL and r.severity == Severity.BLOCKER and "90" in r.message
    nodates = ctx(b=bill(admission_date=None, discharge_date=None), d=None)
    assert TimelyFiling().evaluate(nodates).status == RuleStatus.UNKNOWN


def test_medical_necessity() -> None:
    assert MedicalNecessity().evaluate(ctx()).status == RuleStatus.PASS
    r = MedicalNecessity().evaluate(
        ctx(b=bill(diagnosis_codes=["M17.11"]), d=discharge(diagnosis_codes=[]))
    )
    assert r.status == RuleStatus.FAIL and r.severity == Severity.BLOCKER
    assert (
        MedicalNecessity().evaluate(ctx(b=bill(procedure_code=None))).status == RuleStatus.UNKNOWN
    )
    assert (
        MedicalNecessity()
        .evaluate(ctx(b=bill(diagnosis_codes=[]), d=discharge(diagnosis_codes=[])))
        .status
        == RuleStatus.UNKNOWN
    )  # missing codes are never a pass
    assert (
        MedicalNecessity().evaluate(ctx(b=bill(procedure_code="99999"))).status
        == RuleStatus.UNKNOWN
    )  # no criteria on file: reviewer decides


def test_length_of_stay() -> None:
    assert LengthOfStay().evaluate(ctx()).status == RuleStatus.PASS
    long = bill(discharge_date=date(2025, 3, 12))  # 11 days vs typical 0-3
    r = LengthOfStay().evaluate(ctx(b=long, d=None))
    assert r.status == RuleStatus.FAIL and r.severity == Severity.WARN
    assert LengthOfStay().evaluate(ctx(b=bill(procedure_code=None))).status == RuleStatus.UNKNOWN


def test_accident_liability() -> None:
    assert AccidentLiability().evaluate(ctx()).status == RuleStatus.PASS
    acc = discharge(is_accident=True, third_party_liability=None)
    assert AccidentLiability().evaluate(ctx(d=acc)).status == RuleStatus.UNKNOWN
    assert (
        AccidentLiability()
        .evaluate(ctx(d=discharge(is_accident=True, third_party_liability=True)))
        .status
        == RuleStatus.FAIL
    )
    assert (
        AccidentLiability()
        .evaluate(ctx(d=discharge(is_accident=True, third_party_liability=False)))
        .status
        == RuleStatus.PASS
    )
    assert AccidentLiability().evaluate(ctx(d=None)).status == RuleStatus.UNKNOWN


def test_exclusions() -> None:
    assert (
        Exclusions().evaluate(ctx(b=bill(procedure="Cosmetic rhinoplasty"))).status
        == RuleStatus.FAIL
    )
    assert Exclusions().evaluate(ctx()).status == RuleStatus.PASS
    assert (
        Exclusions().evaluate(ctx(b=bill(diagnosis=None, procedure=None), d=None)).status
        == RuleStatus.UNKNOWN
    )


def test_benefit_limits() -> None:
    bariatric = bill(procedure="Laparoscopic sleeve gastrectomy", total_claimed=45_000)
    r = BenefitLimits().evaluate(ctx(b=bariatric, d=None))
    assert r.status == RuleStatus.FAIL and "$30,000" in r.message
    assert BenefitLimits().evaluate(ctx()).status == RuleStatus.PASS
    assert BenefitLimits().evaluate(ctx(b=bill(total_claimed=None))).status == RuleStatus.UNKNOWN


def test_arithmetic() -> None:
    assert Arithmetic().evaluate(ctx()).status == RuleStatus.PASS
    assert Arithmetic().evaluate(ctx(b=bill(total_claimed=12_500))).status == RuleStatus.FAIL
    bad_line = bill(
        line_items=[LineItem(description="X", quantity=3, unit_price=100, amount=500)],
        total_claimed=500,
    )
    assert Arithmetic().evaluate(ctx(b=bad_line)).status == RuleStatus.FAIL
    assert Arithmetic().evaluate(ctx(b=bill(line_items=[]))).status == RuleStatus.UNKNOWN
    assert (
        Arithmetic().evaluate(ctx(b=bill(unparsed_rows=["3 | Surgeon | 1 | 5,0O0.00"]))).status
        == RuleStatus.UNKNOWN
    )  # unreadable row: cannot verify


def test_dates() -> None:
    assert Dates().evaluate(ctx()).status == RuleStatus.PASS
    assert (
        Dates().evaluate(ctx(b=bill(discharge_date=date(2025, 2, 1)), d=None)).severity
        == Severity.BLOCKER
    )
    assert (
        Dates().evaluate(ctx(b=bill(discharge_date=date(2030, 1, 1)), d=None)).status
        == RuleStatus.FAIL
    )
    assert (
        Dates().evaluate(ctx(d=discharge(discharge_date=date(2025, 3, 5)))).status
        == RuleStatus.FAIL
    )
    assert (
        Dates().evaluate(ctx(b=bill(admission_date=None, discharge_date=None), d=None)).status
        == RuleStatus.UNKNOWN
    )


def test_documents_complete() -> None:
    assert DocumentsComplete().evaluate(ctx()).status == RuleStatus.PASS
    r = DocumentsComplete().evaluate(ctx(docs=(DocumentType.HOSPITAL_BILL,)))
    assert r.status == RuleStatus.FAIL and "discharge summary" in r.message


def test_prior_authorization() -> None:
    big = bill(total_claimed=250_000)
    planned = discharge(is_emergency=False)
    assert PriorAuth().evaluate(ctx(b=big, d=planned)).status == RuleStatus.FAIL
    assert (
        PriorAuth().evaluate(ctx(b=big, d=planned, has_preauth_approval=True)).status
        == RuleStatus.PASS
    )
    assert (
        PriorAuth().evaluate(ctx(b=big, d=discharge(is_emergency=True))).status == RuleStatus.PASS
    )
    assert (
        PriorAuth().evaluate(ctx(b=big, d=discharge(is_emergency=None))).status
        == RuleStatus.UNKNOWN
    )
    assert PriorAuth().evaluate(ctx()).status == RuleStatus.PASS
    listed = bill(procedure="Total knee arthroplasty", total_claimed=20_000)  # on the keyword list
    assert PriorAuth().evaluate(ctx(b=listed, d=planned)).status == RuleStatus.FAIL


def test_network_status() -> None:
    assert (
        NetworkStatus().evaluate(ctx(p=policy(network_providers=[]))).status == RuleStatus.UNKNOWN
    )
    assert NetworkStatus().evaluate(ctx()).status == RuleStatus.PASS
    other = policy(network_providers=["Other Hospital"])
    planned = discharge(is_emergency=False)
    ppo = NetworkStatus().evaluate(ctx(p=other, d=planned))
    assert ppo.status == RuleStatus.FAIL and ppo.severity == Severity.WARN  # PPO: pays less
    hmo = NetworkStatus().evaluate(
        ctx(p=policy("hmo_silver", network_providers=["Other Hospital"]), d=planned)
    )
    assert hmo.status == RuleStatus.FAIL and hmo.severity == Severity.BLOCKER  # HMO: pays nothing
    er = NetworkStatus().evaluate(ctx(p=policy("hmo_silver", network_providers=["Other Hospital"])))
    assert er.status == RuleStatus.PASS and "No Surprises Act" in er.message


def test_code_formats() -> None:
    assert CodeFormats().evaluate(ctx()).status == RuleStatus.PASS
    bad_npi = CodeFormats().evaluate(ctx(b=bill(provider_npi="1003000127")))
    assert bad_npi.status == RuleStatus.FAIL and bad_npi.severity == Severity.BLOCKER
    assert CodeFormats().evaluate(ctx(b=bill(diagnosis_codes=["35.80"]))).status == RuleStatus.FAIL
    assert CodeFormats().evaluate(ctx(b=bill(procedure_code="4497"))).status == RuleStatus.FAIL
    none = bill(provider_npi=None, procedure_code=None, diagnosis_codes=[])
    assert (
        CodeFormats().evaluate(ctx(b=none, d=discharge(diagnosis_codes=[]))).status
        == RuleStatus.UNKNOWN
    )


def test_patient_identity() -> None:
    assert PatientIdentity().evaluate(ctx()).status == RuleStatus.PASS
    assert (
        PatientIdentity().evaluate(ctx(d=discharge(patient_name="Maria L Garcia"))).status
        == RuleStatus.PASS
    )  # subset of tokens
    assert (
        PatientIdentity().evaluate(ctx(d=discharge(patient_name="Vikram Joshi"))).status
        == RuleStatus.FAIL
    )
    assert PatientIdentity().evaluate(ctx(d=None)).status == RuleStatus.UNKNOWN


def test_document_integrity() -> None:
    assert DocumentIntegrity().evaluate(ctx()).status == RuleStatus.PASS
    assert (
        DocumentIntegrity()
        .evaluate(ctx(injection_flags=["instruction_override: line 4: ignore ..."]))
        .status
        == RuleStatus.FAIL
    )


class Boom:
    rule_id, title = "RX", "always crashes"

    def evaluate(self, c):  # type: ignore[no-untyped-def]
        raise RuntimeError("bug")


def test_crashing_rule_becomes_unknown_never_pass() -> None:
    results = RuleEngine([Boom()]).run(ctx())
    assert results[0].status == RuleStatus.UNKNOWN and results[0].severity == Severity.WARN


@pytest.mark.parametrize("missing", ["bill", "discharge", "both"])
def test_missing_documents_never_produce_a_clean_pass(missing: str) -> None:
    b = None if missing in ("bill", "both") else "default"
    d = None if missing in ("discharge", "both") else "default"
    results = RuleEngine(default_rules()).run(ctx(b=b, d=d))
    assert any(r.status != RuleStatus.PASS for r in results)
    assert all(
        r.status != RuleStatus.PASS
        for r in results
        if r.rule_id in {"R004", "R006", "R008", "R018"} and b is None
    )
