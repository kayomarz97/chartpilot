"""Normalized clinical models and their supporting enums.

These are the trustworthy, precision-preserving shapes that Phase 4 turns
raw FHIR resources into. Nothing downstream (rules in Phase 5, evidence in
Phase 6) should ever read a raw FHIR dict directly -- it reads these models.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.normalize.temporal import ClinicalInstant
from app.normalize.units import NormalizedQuantity


class ObservationStatus(StrEnum):
    """Mirrors FHIR `Observation.status`.

    FHIR's `entered-in-error` (with a hyphen, not a valid Python enum member
    name) is mapped to `entered_in_error` at parse time in `observation.py`.
    """

    REGISTERED = "registered"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    CORRECTED = "corrected"
    CANCELLED = "cancelled"
    ENTERED_IN_ERROR = "entered_in_error"
    UNKNOWN = "unknown"


class AbnormalityBasis(StrEnum):
    """Why a value was (or would be) flagged abnormal.

    Only the enum exists in Phase 4 -- the precedence logic that decides
    which basis wins when several are available is Phase 5's job.
    """

    REFERENCE_RANGE = "reference_range"
    INTERPRETATION = "interpretation"
    CONFIGURED_DEMO_THRESHOLD = "configured_demo_threshold"
    NONE = "none"


class ReferenceRange(BaseModel):
    """A normalized `Observation.referenceRange` entry."""

    model_config = ConfigDict(frozen=True)

    low: NormalizedQuantity | None = None
    high: NormalizedQuantity | None = None
    type_text: str | None = None


class NormalizedComponent(BaseModel):
    """A normalized `Observation.component` entry (e.g. one panel member)."""

    model_config = ConfigDict(frozen=True)

    code: str
    value: NormalizedQuantity | str | None
    interpretation: list[str]
    reference_ranges: list[ReferenceRange]
    data_absent_reason: str | None


class NarrativeNote(BaseModel):
    """A free-text `Observation.note` / similar narrative annotation.

    `trusted` is always `False` and cannot be constructed otherwise: free
    text narrative is never treated as a clinical fact by this system (spec
    §53 foundation). It may be shown to a clinician for context, but nothing
    downstream may reason over it as structured data.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    trusted: Literal[False] = False


class NormalizedObservation(BaseModel):
    """A fully normalized `Observation` resource."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    code_system: str | None
    display: str | None
    status: ObservationStatus
    value: NormalizedQuantity | str | None
    data_absent_reason: str | None
    interpretation: list[str]
    reference_ranges: list[ReferenceRange]
    components: list[NormalizedComponent]
    effective: ClinicalInstant
    issued: ClinicalInstant | None
    notes: list[NarrativeNote]
    source_resource_id: str
    normalization_warnings: list[str]
