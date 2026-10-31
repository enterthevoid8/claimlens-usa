"""Rule interface and engine. A rule can say pass, fail, or unknown: never guess."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from claimlens.domain.models import (
    DocumentRef,
    DocumentType,
    ExtractedClaimData,
    Policy,
    RuleResult,
    RuleStatus,
    Severity,
)

log = logging.getLogger(__name__)


@dataclass
class RuleContext:
    policy: Policy
    data: ExtractedClaimData
    documents: list[DocumentRef] = field(default_factory=list)
    today: date = field(default_factory=date.today)

    @property
    def present_types(self) -> set[DocumentType]:
        return {d.doc_type for d in self.documents if d.doc_type is not None}

    @property
    def diagnosis_text(self) -> str:
        parts: list[str | None] = []
        if self.data.bill:
            parts += [self.data.bill.diagnosis, self.data.bill.procedure]
        if self.data.discharge:
            parts += [self.data.discharge.diagnosis, self.data.discharge.procedure]
        return " ".join(p.lower() for p in parts if p)

    @property
    def admission_date(self) -> date | None:
        for src in (self.data.bill, self.data.discharge):
            if src is not None and src.admission_date:
                return src.admission_date
        return None

    @property
    def discharge_date(self) -> date | None:
        for src in (self.data.bill, self.data.discharge):
            if src is not None and src.discharge_date:
                return src.discharge_date
        return None


class Rule(Protocol):
    rule_id: str
    title: str

    def evaluate(self, ctx: RuleContext) -> RuleResult: ...


class RuleEngine:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for rule in self.rules:
            try:
                results.append(rule.evaluate(ctx))
            except Exception:
                # A crashing rule must never read as a pass.
                log.exception("rule %s crashed", rule.rule_id)
                results.append(
                    RuleResult(
                        rule_id=rule.rule_id,
                        title=rule.title,
                        status=RuleStatus.UNKNOWN,
                        severity=Severity.WARN,
                        message="This check could not be completed; treat it as unverified.",
                    )
                )
        return results
