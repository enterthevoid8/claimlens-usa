"""Built-in rules. Each one cites the policy clause it enforces and the evidence it used."""

from __future__ import annotations

import math
from datetime import timedelta
from difflib import SequenceMatcher

from claimlens.domain.models import (
    DocumentType,
    Evidence,
    RuleResult,
    RuleStatus,
    Severity,
)
from claimlens.extraction.parsing import normalize_name
from claimlens.rules.base import Rule, RuleContext
from claimlens.rules.coding import (
    dx_supports,
    is_valid_icd10,
    is_valid_npi,
    is_valid_procedure_code,
    lookup,
    normalize_code,
)

PASS, FAIL, UNKNOWN = RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.UNKNOWN


def _res(
    rule: Rule,
    status: RuleStatus,
    message: str,
    severity: Severity = Severity.INFO,
    clause: str | None = None,
    evidence: list[Evidence] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        title=rule.title,
        status=status,
        severity=severity if status != PASS else Severity.INFO,
        message=message,
        clause=clause,
        evidence=evidence or [],
    )


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _fmt(x: float) -> str:
    return f"${x:,.0f}"


def _name_similarity(a: str | None, b: str | None) -> float | None:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return None
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _same_provider(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    return bool(
        na and nb and (na in nb or nb in na or SequenceMatcher(None, na, nb).ratio() >= 0.85)
    )


class CoveragePeriod:
    rule_id, title = "R001", "Service falls within the coverage period"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        adm = ctx.admission_date
        if adm is None:
            return _res(self, UNKNOWN, "Admission date could not be read.", Severity.WARN, "1.2")
        p = ctx.policy
        ev = [Evidence(field="admission_date", text=adm.isoformat())]
        if adm < p.start_date or adm > p.end_date:
            return _res(
                self,
                FAIL,
                f"Service on {adm:%m/%d/%Y} is outside the coverage period {p.start_date:%m/%d/%Y} to {p.end_date:%m/%d/%Y}.",
                Severity.BLOCKER,
                "1.2",
                ev,
            )
        return _res(self, PASS, "Service is within the coverage period.", clause="1.2", evidence=ev)


class EligibilityWaiting:
    rule_id, title = "R002", "Eligibility waiting period served"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        adm, p = ctx.admission_date, ctx.policy
        if p.waiting_period_days <= 0:
            return _res(self, PASS, "The plan has no eligibility waiting period.", clause="2.1")
        if adm is None:
            return _res(self, UNKNOWN, "Admission date could not be read.", Severity.WARN, "2.1")
        days = (adm - p.start_date).days
        if days >= p.waiting_period_days:
            return _res(
                self,
                PASS,
                f"Service is {days} days after the coverage effective date (waiting period {p.waiting_period_days} days).",
                clause="2.1",
            )
        return _res(
            self,
            FAIL,
            f"Service is {days} days after the coverage effective date, inside the {p.waiting_period_days}-day eligibility waiting period; coverage was not yet active.",
            Severity.BLOCKER,
            "2.1",
        )


class TimelyFiling:
    rule_id, title = "R003", "Claim is filed within the timely-filing limit"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        dis, p = ctx.discharge_date or ctx.admission_date, ctx.policy
        if dis is None:
            return _res(self, UNKNOWN, "Service dates could not be read.", Severity.WARN, "2.2")
        deadline = dis + timedelta(days=p.timely_filing_days)
        lag = (ctx.today - dis).days
        if lag > p.timely_filing_days:
            return _res(
                self,
                FAIL,
                f"Filed {lag} days after discharge; the plan's limit is {p.timely_filing_days} days (deadline was {deadline:%m/%d/%Y}).",
                Severity.BLOCKER,
                "2.2",
                [Evidence(field="discharge_date", text=dis.isoformat())],
            )
        return _res(
            self,
            PASS,
            f"Filing deadline is {deadline:%m/%d/%Y} ({max(p.timely_filing_days - lag, 0)} days left).",
            clause="2.2",
        )


class MedicalNecessity:
    rule_id, title = "R004", "Diagnosis supports the procedure"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        b, d = ctx.data.bill, ctx.data.discharge
        code = normalize_code(b.procedure_code if b else None)
        dx = [
            x for x in ((b.diagnosis_codes if b else []) or (d.diagnosis_codes if d else [])) if x
        ]
        if not code:
            return _res(self, UNKNOWN, "No procedure code could be read.", Severity.WARN, "2.3")
        if not dx:
            return _res(self, UNKNOWN, "No diagnosis codes could be read.", Severity.WARN, "2.3")
        edit = lookup(code)
        verdict = dx_supports(code, dx)
        if edit is None or verdict is None:
            return _res(
                self,
                UNKNOWN,
                f"No coverage criteria are on file for {code}; a reviewer should check medical necessity.",
                Severity.INFO,
                "2.3",
            )
        ev = [
            Evidence(
                document_id=b.document_id if b else None,
                field="diagnosis_codes",
                text=", ".join(dx),
            )
        ]
        if verdict:
            return _res(
                self,
                PASS,
                f"Diagnosis {dx[0]} supports {edit.description} ({code}).",
                clause="2.3",
                evidence=ev,
            )
        families = ", ".join(edit.dx_prefixes)
        return _res(
            self,
            FAIL,
            f"Diagnosis {', '.join(dx)} does not support {edit.description} ({code}); expected a diagnosis in {families}. Expect a medical-necessity denial.",
            Severity.BLOCKER,
            "2.3",
            ev,
        )


class Exclusions:
    rule_id, title = "R005", "Plan exclusions"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        text = ctx.diagnosis_text
        if not text:
            return _res(
                self, UNKNOWN, "Diagnosis and procedure could not be read.", Severity.WARN, "3.1"
            )
        for ex in ctx.policy.exclusions:
            if any(k in text for k in ex.keywords):
                return _res(
                    self,
                    FAIL,
                    f"Matches exclusion '{ex.title}'.",
                    Severity.BLOCKER,
                    ex.clause,
                    [Evidence(field="diagnosis", text=text[:160])],
                )
        return _res(
            self, PASS, "No exclusion keywords matched the diagnosis or procedure.", clause="3.1"
        )


class LengthOfStay:
    rule_id, title = "R006", "Length of stay is typical for the procedure"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bill = ctx.data.bill
        adm, dis = ctx.admission_date, ctx.discharge_date
        if adm is None or dis is None or dis < adm:
            return _res(
                self, UNKNOWN, "Length of stay could not be determined.", Severity.WARN, "4.1"
            )
        edit = lookup(bill.procedure_code if bill else None)
        if edit is None:
            return _res(
                self,
                UNKNOWN,
                "No typical length of stay is on file for this procedure.",
                Severity.INFO,
                "4.1",
            )
        los = (dis - adm).days
        lo, hi = edit.typical_los
        limit = hi + max(1, math.ceil(0.5 * hi))
        if los > limit:
            return _res(
                self,
                FAIL,
                f"Stay of {los} days is well beyond the typical {lo}-{hi} days for {edit.description}; expect a continued-stay review of the extra days.",
                Severity.WARN,
                "4.1",
                [Evidence(field="length_of_stay", text=f"{los} days")],
            )
        return _res(
            self,
            PASS,
            f"Stay of {los} day(s) is within the typical {lo}-{hi} days for {edit.description}.",
            clause="4.1",
        )


class AccidentLiability:
    rule_id, title = "R007", "Accident and third-party liability"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        d = ctx.data.discharge
        if d is None:
            return _res(
                self,
                UNKNOWN,
                "No discharge summary, so the cause cannot be checked.",
                Severity.WARN,
                "5.4",
            )
        if d.is_accident is None:
            return _res(
                self,
                UNKNOWN,
                "The cause (accident or illness) is not stated.",
                Severity.WARN,
                "5.4",
            )
        if not d.is_accident:
            return _res(
                self,
                PASS,
                "Not accident-related; no coordination of benefits expected.",
                clause="5.4",
            )
        if d.third_party_liability is True:
            return _res(
                self,
                FAIL,
                "Accident with a possible liable third party (for example auto or premises insurance). The plan may pend the claim for coordination of benefits or subrogation.",
                Severity.WARN,
                "5.4",
            )
        if d.third_party_liability is None:
            return _res(
                self,
                UNKNOWN,
                "Accident-related claim and the documents do not say whether another party's insurance is primary; the plan will usually send an accident questionnaire.",
                Severity.WARN,
                "5.4",
            )
        return _res(self, PASS, "Accident with no third-party liability stated.", clause="5.4")


class Arithmetic:
    rule_id, title = "R008", "Bill arithmetic is consistent"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bill = ctx.data.bill
        if (
            bill is None
            or bill.total_claimed is None
            or not (bill.line_items or bill.unparsed_rows)
        ):
            return _res(
                self,
                UNKNOWN,
                "Line items or the total could not be read, so the arithmetic cannot be verified.",
                Severity.WARN,
            )
        if bill.unparsed_rows:
            return _res(
                self,
                UNKNOWN,
                f"{len(bill.unparsed_rows)} bill line(s) could not be read (e.g. '{bill.unparsed_rows[0][:60]}'), so the total cannot be verified. Please check the original.",
                Severity.WARN,
                evidence=[
                    Evidence(document_id=bill.document_id, field="line_item", text=r)
                    for r in bill.unparsed_rows[:3]
                ],
            )
        problems: list[str] = []
        s = round(sum(i.amount for i in bill.line_items), 2)
        tol = max(1.0, 0.005 * bill.total_claimed)
        if abs(s - bill.total_claimed) > tol:
            problems.append(
                f"line items add up to {_fmt(s)} but the bill total is {_fmt(bill.total_claimed)}"
            )
        bad = [
            i
            for i in bill.line_items
            if i.unit_price is not None
            and abs(i.quantity * i.unit_price - i.amount) > max(1.0, 0.005 * i.amount)
        ]
        if bad:
            problems.append(
                f"{len(bad)} line(s) where quantity x rate does not equal the amount (e.g. '{bad[0].description}')"
            )
        if problems:
            return _res(
                self,
                FAIL,
                _cap("; ".join(problems)) + ".",
                Severity.WARN,
                evidence=[
                    Evidence(
                        document_id=bill.document_id,
                        field="total_claimed",
                        text=str(bill.total_claimed),
                    )
                ],
            )
        return _res(self, PASS, "Line items add up to the bill total.")


class Dates:
    rule_id, title = "R009", "Dates are consistent"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        b, d = ctx.data.bill, ctx.data.discharge
        adm, dis = ctx.admission_date, ctx.discharge_date
        if adm is None or dis is None:
            return _res(
                self, UNKNOWN, "Admission or discharge date could not be read.", Severity.WARN
            )
        if dis < adm:
            return _res(
                self, FAIL, f"Discharge ({dis}) is before admission ({adm}).", Severity.BLOCKER
            )
        if dis > ctx.today:
            return _res(self, FAIL, f"Discharge date {dis} is in the future.", Severity.BLOCKER)
        if (
            b
            and d
            and b.admission_date
            and d.admission_date
            and b.admission_date != d.admission_date
        ):
            return _res(
                self,
                FAIL,
                f"Bill admission date {b.admission_date} differs from the discharge summary {d.admission_date}.",
                Severity.WARN,
            )
        if (
            b
            and d
            and b.discharge_date
            and d.discharge_date
            and b.discharge_date != d.discharge_date
        ):
            return _res(
                self,
                FAIL,
                f"Bill discharge date {b.discharge_date} differs from the discharge summary {d.discharge_date}.",
                Severity.WARN,
            )
        return _res(
            self, PASS, f"Stay of {(dis - adm).days} day(s); dates are consistent across documents."
        )


class DocumentsComplete:
    rule_id, title = "R010", "Required documents present"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        missing = [t for t in ctx.policy.required_documents if t not in ctx.present_types]
        if missing:
            names = ", ".join(t.value.replace("_", " ") for t in missing)
            return _res(self, FAIL, f"Missing: {names}.", Severity.BLOCKER, "5.2")
        return _res(self, PASS, "All required documents are present.", clause="5.2")


class PriorAuth:
    rule_id, title = "R011", "Prior authorization"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bill, d, p = ctx.data.bill, ctx.data.discharge, ctx.policy
        if bill is None or bill.total_claimed is None:
            return _res(self, UNKNOWN, "Billed total could not be read.", Severity.WARN, "5.1")
        text = ctx.diagnosis_text
        listed = next((k for k in p.preauth_keywords if k in text), None)
        if not listed and bill.total_claimed <= p.preauth_required_above:
            return _res(
                self,
                PASS,
                f"Prior authorization is not required (below {_fmt(p.preauth_required_above)} and not a listed service).",
                clause="5.1",
            )
        why = (
            f"'{listed}' is on the plan's prior-authorization list"
            if listed
            else (
                f"the billed total {_fmt(bill.total_claimed)} is above {_fmt(p.preauth_required_above)}"
            )
        )
        if ctx.data.has_preauth_approval:
            return _res(
                self, PASS, f"A prior authorization approval was provided ({why}).", clause="5.1"
            )
        emergency = d.is_emergency if d else None
        if emergency is True:
            return _res(
                self, PASS, "Emergency services do not require prior authorization.", clause="5.1"
            )
        if emergency is None:
            return _res(
                self,
                UNKNOWN,
                f"Prior authorization is needed for planned care ({why}); the admission type is not stated and no approval was provided.",
                Severity.WARN,
                "5.1",
            )
        return _res(
            self,
            FAIL,
            f"Planned care needs prior authorization ({why}) and no approval is attached.",
            Severity.BLOCKER,
            "5.1",
        )


class NetworkStatus:
    rule_id, title = "R012", "Provider network status"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bill, p = ctx.data.bill, ctx.policy
        nets = p.network_providers
        if not nets:
            return _res(
                self,
                UNKNOWN,
                "No provider network is configured for this plan.",
                Severity.INFO,
                "5.3",
            )
        if bill is None or not bill.hospital_name:
            return _res(self, UNKNOWN, "Provider name could not be read.", Severity.WARN, "5.3")
        if any(_same_provider(bill.hospital_name, n) for n in nets):
            return _res(self, PASS, "Provider is in the plan's network.", clause="5.3")
        d = ctx.data.discharge
        if d is not None and d.is_emergency is True:
            return _res(
                self,
                PASS,
                f"'{bill.hospital_name}' is out of network, but emergency services are protected under the No Surprises Act: in-network cost-sharing applies and balance billing is prohibited.",
                clause="5.3",
            )
        if p.plan_type.requires_network:
            return _res(
                self,
                FAIL,
                f"'{bill.hospital_name}' is out of network and this {p.plan_type.value} plan pays nothing for non-emergency out-of-network care without an approved referral.",
                Severity.BLOCKER,
                "5.3",
            )
        return _res(
            self,
            FAIL,
            f"'{bill.hospital_name}' is out of network: higher cost-sharing applies and the member may be balance billed.",
            Severity.WARN,
            "5.3",
        )


class BenefitLimits:
    rule_id, title = "R013", "Benefit limits"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bill, text = ctx.data.bill, ctx.diagnosis_text
        if bill is None or bill.total_claimed is None or not text:
            return _res(
                self, UNKNOWN, "Procedure or total could not be read.", Severity.WARN, "6.1"
            )
        for s in ctx.policy.benefit_limits:
            if any(k in text for k in s.keywords):
                if bill.total_claimed > s.max_amount:
                    return _res(
                        self,
                        FAIL,
                        f"{s.procedure} has a benefit maximum of {_fmt(s.max_amount)}; billed {_fmt(bill.total_claimed)}. The excess is the member's responsibility.",
                        Severity.WARN,
                        s.clause,
                    )
                return _res(
                    self,
                    PASS,
                    f"{s.procedure} is within its benefit maximum of {_fmt(s.max_amount)}.",
                    clause=s.clause,
                )
        return _res(self, PASS, "No benefit maximum applies to this service.", clause="6.1")


class PatientIdentity:
    rule_id, title = "R014", "Patient name matches across documents"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        b, d = ctx.data.bill, ctx.data.discharge
        if b is None or d is None:
            return _res(
                self, UNKNOWN, "Needs both the bill and the discharge summary.", Severity.WARN
            )
        sim = _name_similarity(b.patient_name, d.patient_name)
        if sim is None:
            return _res(self, UNKNOWN, "Patient name missing on one document.", Severity.WARN)
        if sim >= 0.85:
            return _res(self, PASS, "Patient name matches on the bill and the discharge summary.")
        if sim < 0.6:
            return _res(
                self,
                FAIL,
                f"Patient name differs: '{b.patient_name}' on the bill vs '{d.patient_name}' on the discharge summary.",
                Severity.BLOCKER,
            )
        return _res(
            self,
            UNKNOWN,
            "Patient names are similar but not identical; please verify.",
            Severity.WARN,
        )


class DocumentIntegrity:
    rule_id, title = "R015", "Documents contain no embedded instructions"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        flags = ctx.data.injection_flags
        if flags:
            return _res(
                self,
                FAIL,
                f"{len(flags)} suspicious passage(s) found in the uploaded documents. They were treated as plain text and ignored; a reviewer should inspect them.",
                Severity.WARN,
                evidence=[Evidence(text=f[:200]) for f in flags[:5]],
            )
        return _res(self, PASS, "No embedded instructions or hidden text found.")


class ExtractionQuality:
    rule_id, title = "R016", "Extraction confidence"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        c = ctx.data.extraction_confidence
        if c < 0.6:
            return _res(
                self,
                UNKNOWN,
                f"Only {c:.0%} of expected fields were read. Verify the source documents manually.",
                Severity.WARN,
            )
        return _res(self, PASS, f"{c:.0%} of expected fields were read.")


class Readable:
    rule_id, title = "R017", "All uploaded files could be read"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        bad = ctx.data.unreadable_documents
        if bad:
            return _res(
                self,
                FAIL,
                f"{len(bad)} file(s) could not be read: "
                + "; ".join(bad[:3])
                + ". Please upload a clearer copy.",
                Severity.WARN,
                "5.2",
            )
        return _res(self, PASS, "All uploaded files could be read.")


class CodeFormats:
    rule_id, title = "R018", "Provider NPI and codes are well-formed"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        b = ctx.data.bill
        if b is None:
            return _res(self, UNKNOWN, "No bill available.", Severity.WARN)
        dx = b.diagnosis_codes or (ctx.data.discharge.diagnosis_codes if ctx.data.discharge else [])
        if not (b.provider_npi or b.procedure_code or dx):
            return _res(
                self,
                UNKNOWN,
                "No NPI or diagnosis/procedure codes could be read, so the claim cannot be checked against clearinghouse edits.",
                Severity.WARN,
            )
        problems: list[str] = []
        if b.provider_npi and not is_valid_npi(b.provider_npi):
            problems.append(f"NPI {b.provider_npi} fails the check-digit test")
        if not b.provider_npi:
            problems.append("the facility NPI is missing")
        if b.procedure_code and not is_valid_procedure_code(b.procedure_code):
            problems.append(
                f"procedure code '{b.procedure_code}' is not a valid CPT, HCPCS or DRG code"
            )
        bad_dx = [x for x in dx if not is_valid_icd10(x)]
        if bad_dx:
            problems.append(f"diagnosis code(s) {', '.join(bad_dx)} are not valid ICD-10-CM")
        if problems:
            return _res(
                self,
                FAIL,
                _cap("; ".join(problems))
                + ". A clearinghouse would reject the claim before it reaches the plan.",
                Severity.BLOCKER,
                evidence=[
                    Evidence(
                        document_id=b.document_id,
                        field="codes",
                        text=f"NPI {b.provider_npi}; {b.procedure_code}; {', '.join(dx)}",
                    )
                ],
            )
        return _res(self, PASS, "NPI and diagnosis/procedure codes are well-formed.")


def default_rules() -> list[Rule]:
    return [
        CoveragePeriod(),
        EligibilityWaiting(),
        TimelyFiling(),
        MedicalNecessity(),
        Exclusions(),
        LengthOfStay(),
        AccidentLiability(),
        Arithmetic(),
        Dates(),
        DocumentsComplete(),
        PriorAuth(),
        NetworkStatus(),
        BenefitLimits(),
        PatientIdentity(),
        DocumentIntegrity(),
        ExtractionQuality(),
        Readable(),
        CodeFormats(),
    ]


def missing_documents(ctx: RuleContext) -> list[DocumentType]:
    return [t for t in ctx.policy.required_documents if t not in ctx.present_types]
