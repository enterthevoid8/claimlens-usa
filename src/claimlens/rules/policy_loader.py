"""Policy products live in YAML so a domain expert can review and change them without touching code."""

from __future__ import annotations

from datetime import date
from importlib import resources
from typing import Any

import yaml
from pydantic import BaseModel, Field

from claimlens.domain.models import BenefitLimit, Exclusion, PlanType, Policy


class ProductTemplate(BaseModel):
    product_name: str
    plan_type: PlanType = PlanType.PPO
    waiting_period_days: int = 0
    timely_filing_days: int = 180
    deductible: float = 0.0
    coinsurance_pct: float = 0.0
    oop_max: float = 0.0
    preauth_required_above: float = 50_000
    preauth_keywords: list[str] = Field(default_factory=list)
    exclusions: list[dict[str, Any]] = Field(default_factory=list)
    benefit_limits: list[dict[str, Any]] = Field(default_factory=list)


def available_products() -> list[str]:
    root = resources.files("claimlens.rules") / "policies"
    return sorted(p.name.removesuffix(".yaml") for p in root.iterdir() if p.name.endswith(".yaml"))


def load_product(name: str) -> ProductTemplate:
    if name not in available_products():
        raise KeyError(f"unknown product '{name}'")
    text = (resources.files("claimlens.rules") / "policies" / f"{name}.yaml").read_text(
        encoding="utf-8"
    )
    return ProductTemplate.model_validate(yaml.safe_load(text))


def instantiate_policy(
    product: str,
    *,
    policy_id: str,
    tenant_id: str,
    holder_name: str,
    start_date: date,
    network_providers: list[str] | None = None,
    term_years: int = 1,
    insurer: str = "Example Health Plan",
    deductible_met: float = 0.0,
    oop_met: float = 0.0,
) -> Policy:
    t = load_product(product)
    try:
        end = start_date.replace(year=start_date.year + term_years)
    except ValueError:  # 29 Feb
        end = start_date.replace(year=start_date.year + term_years, day=28)
    return Policy(
        policy_id=policy_id,
        tenant_id=tenant_id,
        insurer=insurer,
        product_name=t.product_name,
        plan_type=t.plan_type,
        holder_name=holder_name,
        start_date=start_date,
        end_date=end,
        waiting_period_days=t.waiting_period_days,
        timely_filing_days=t.timely_filing_days,
        deductible=t.deductible,
        deductible_met=min(deductible_met, t.deductible),
        coinsurance_pct=t.coinsurance_pct,
        oop_max=t.oop_max,
        oop_met=min(oop_met, t.oop_max),
        preauth_required_above=t.preauth_required_above,
        preauth_keywords=[k.lower() for k in t.preauth_keywords],
        exclusions=[Exclusion(**e) for e in t.exclusions],
        benefit_limits=[BenefitLimit(**b) for b in t.benefit_limits],
        network_providers=network_providers or [],
    )
