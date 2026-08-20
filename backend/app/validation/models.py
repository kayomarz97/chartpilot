"""Contract and result shapes for the ClinicalValidityEngine.

A `ValidityContract` documents what a derived metric needs and how it is
computed; a `ValidityResult` is what the engine hands back after trying to
evaluate one. Neither type knows anything about a *specific* metric (eGFR,
corrected calcium, ...) -- that specificity lives entirely in
`app.validation.metrics`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ValidityStatus(StrEnum):
    """The outcome of trying to evaluate a derived clinical metric."""

    VALID = "valid"
    VALID_WITH_LIMITATIONS = "valid_with_limitations"
    INVALID = "invalid"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_REVIEW = "requires_review"


class ValidityContract(BaseModel):
    """Declares what a derived metric needs and how it is computed.

    Preconditions/exclusions beyond "are the required inputs present" (e.g.
    eGFR's steady-state creatinine check) are NOT expressed here -- they are
    implemented inside the registered evaluator callable, since they are
    metric-specific logic the generic engine must not know about.
    """

    model_config = ConfigDict(frozen=True)

    metric_id: str
    version: str
    required_inputs: tuple[str, ...]
    required_units: dict[str, str]
    formula_or_method: str
    supporting_sources: tuple[str, ...]
    effective_date: str


class ValidityResult(BaseModel):
    """The outcome of one `ClinicalValidityEngine.evaluate(...)` call."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    version: str
    status: ValidityStatus
    value: Decimal | None
    unit: str | None
    failed_preconditions: tuple[str, ...]
    limitations: tuple[str, ...]
    detail: str | None
