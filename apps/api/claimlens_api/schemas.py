from __future__ import annotations

from pydantic import BaseModel, Field

from claimlens.domain.models import DecisionType


class CreateClaim(BaseModel):
    policy_id: str = Field(min_length=1, max_length=64)
    consent_given: bool


class ExplainRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DecisionRequest(BaseModel):
    decision: DecisionType
    note: str = Field(default="", max_length=2000)
