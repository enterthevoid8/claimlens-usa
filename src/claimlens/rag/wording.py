"""Render a ``Policy`` into clause-structured plan wording.

The same ``Policy`` object drives both the rules and this text, so the answers the explainer cites can
never drift from what the rules enforce. Real deployments would index the plan's own Evidence of Coverage /
Summary Plan Description instead (chunked by clause with the same ``chunk_policy_wording`` function).
"""

from __future__ import annotations

from claimlens.domain.models import PlanType, Policy


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def render_policy_wording(p: Policy) -> str:
    lines: list[str] = [
        f"# {p.product_name}: Plan Wording",
        f"Plan {p.policy_id}. Subscriber {p.holder_name}. Plan type {p.plan_type.value}. Health plan {p.insurer}.",
        "",
        "## Clause 1.1 Deductible, Coinsurance and Out-of-Pocket Maximum",
        f"You pay the first {_usd(p.deductible)} of covered charges each plan year (the deductible) before the plan starts to pay, "
        f"then {p.coinsurance_pct:g}% coinsurance on covered charges until you reach the annual out-of-pocket maximum of {_usd(p.oop_max)}. "
        "After the out-of-pocket maximum is reached the plan pays 100% of covered in-network essential health benefits for the rest of the plan year. "
        "Premiums, balance-billed amounts from out-of-network providers and services that are not covered do not count toward the out-of-pocket maximum.",
        "",
        "## Clause 1.2 Coverage Period",
        f"Coverage starts on {p.start_date:%B %d, %Y} and ends on {p.end_date:%B %d, %Y}. "
        "Only services received within this period are covered.",
        "",
        "## Clause 2.1 Eligibility Waiting Period",
        f"Coverage begins after an eligibility waiting period of {p.waiting_period_days} days from the coverage effective date. "
        "Services received during the waiting period are not covered. Pre-existing conditions are never excluded or waited out.",
        "",
        "## Clause 2.2 Timely Filing",
        f"Claims must be filed within {p.timely_filing_days} days of the date of discharge or date of service. "
        "Claims filed after this limit are denied and the member cannot be billed for them when the provider was at fault.",
        "",
        "## Clause 2.3 Medical Necessity",
        "The plan pays only for services that are medically necessary. The diagnosis reported on the claim must support the procedure billed. "
        "The plan may deny or pend claims where the diagnosis codes do not support the procedure code.",
        "",
        "## Clause 3.1 Exclusions",
        "The plan does not cover the following.",
    ]
    for e in p.exclusions:
        lines.append(f"- Clause {e.clause}: {e.title}. Related terms: {', '.join(e.keywords)}.")
    lines += [
        "",
        "## Clause 4.1 Length of Stay and Continued-Stay Review",
        "Inpatient days are reviewed against clinical guidelines for the procedure or diagnosis. "
        "Days beyond the expected length of stay need documented clinical justification, or the extra days may be denied.",
        "",
        "## Clause 4.2 Emergency Room Services",
        "Emergency services are covered without prior authorization at in-network cost-sharing, regardless of where they are received, "
        "as required by the No Surprises Act.",
        "",
        "## Clause 5.1 Prior Authorization",
        f"Planned (non-emergency) admissions and procedures need prior authorization from the plan before the service when the expected charges are above {_usd(p.preauth_required_above)}"
        + (
            f" or when the service is on the plan's list: {', '.join(p.preauth_keywords)}."
            if p.preauth_keywords
            else "."
        )
        + " Emergency admissions do not need prior authorization. Services without a required prior authorization may be denied.",
        "",
        "## Clause 5.2 Documents Required",
        "Submit these documents with every claim: "
        + ", ".join(d.value.replace("_", " ") for d in p.required_documents)
        + ". The plan may ask for more documents, such as medical records, lab reports or a prior authorization letter.",
        "",
        "## Clause 5.3 Provider Network",
    ]
    if p.plan_type.requires_network:
        lines.append(
            f"This {p.plan_type.value} plan covers care only from in-network providers, except for emergency services. "
            "Non-emergency out-of-network care is not covered unless the plan approves a referral in advance."
        )
    else:
        lines.append(
            f"This {p.plan_type.value} plan covers out-of-network care at a lower level: higher cost-sharing applies and the provider may bill you for the difference "
            "between its charge and the plan's allowed amount (balance billing), except for emergency services and certain services at in-network facilities, "
            "which are protected under the No Surprises Act."
        )
    lines += [
        "",
        "## Clause 5.4 Accidents and Third-Party Liability",
        "If an injury was caused by an accident, the plan may ask for details and may coordinate benefits with another insurer (such as auto or homeowner coverage) "
        "that is primary. The plan can recover payments from a liable third party (subrogation). Claims may be pended until accident information is received.",
        "",
        "## Clause 6.1 Benefit Limits",
    ]
    if p.benefit_limits:
        lines.append("Some services have a maximum benefit:")
        for s in p.benefit_limits:
            lines.append(
                f"- {s.procedure}: up to {_usd(s.max_amount)} per claim. Related terms: {', '.join(s.keywords)}."
            )
    else:
        lines.append("No service-specific benefit maximums apply.")
    appeals = (
        "You can appeal any denial within 180 days and request an independent external review."
        if p.plan_type != PlanType.HMO
        else "You can appeal any denial within 180 days and request an independent external review of the final decision."
    )
    lines += [
        "",
        "## Clause 7.1 How Claims Are Assessed and Appeals",
        "Every claim is assessed by a human claims reviewer. Automated checks only highlight missing documents and possible issues. "
        + appeals
        + " The plan must explain every denial in an Explanation of Benefits.",
        "",
    ]
    return "\n".join(lines)
