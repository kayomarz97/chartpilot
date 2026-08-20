"""Shared result/verdict shapes for clinical safety rules.

`AbnormalityBasis` is intentionally re-used from `app.normalize.models`
rather than redefined here -- Phase 4 already declared the enum; Phase 5
(`app.rules.abnormality`) adds the precedence logic that decides which basis
wins.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.normalize.models import AbnormalityBasis

__all__ = [
    "RuleVerdict",
    "Severity",
    "AbnormalityBasis",
    "AbnormalityAssessment",
    "RuleResult",
]


class RuleVerdict(StrEnum):
    """The outcome of evaluating one clinical safety rule."""

    FIRED = "fired"
    NOT_FIRED = "not_fired"
    REQUIRES_REVIEW = "requires_review"
    INSUFFICIENT_DATA = "insufficient_data"


class Severity(StrEnum):
    """Clinical severity of a fired rule."""

    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INFO = "info"


class AbnormalityAssessment(BaseModel):
    """The result of applying the §29 abnormality precedence to one value."""

    model_config = ConfigDict(frozen=True)

    is_abnormal: bool
    direction: Literal["high", "low", "normal", "unknown"]
    basis: AbnormalityBasis
    detail: str


class RuleResult(BaseModel):
    """The outcome of evaluating one clinical safety rule against a chart."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    rule_version: str
    verdict: RuleVerdict
    severity: Severity | None
    matched_observation_ids: tuple[str, ...]
    matched_medication_ids: tuple[str, ...]
    normalized_values: dict[str, str]
    abnormality_basis: AbnormalityBasis
    matched_effective_times: tuple[str, ...]
    rationale: str
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def _reject_naive(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("RuleResult.evaluated_at must be tz-aware; got a naive datetime")
        return v
