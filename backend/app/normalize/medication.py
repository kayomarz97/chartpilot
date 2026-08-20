"""Normalize FHIR `MedicationRequest` resources into medication orders.

An order is a prescriber's instruction, not proof of what actually happened
to the patient. This module normalizes the order itself and deliberately
stops there -- see `NormalizedMedicationOrder`'s docstring.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.normalize.temporal import ClinicalInstant, absent_instant, parse_fhir_datetime


class MedicationOrderStatus(StrEnum):
    """Mirrors FHIR `MedicationRequest.status`.

    FHIR's hyphenated codes (`on-hold`, `entered-in-error`) are mapped to
    underscored member values at parse time, consistent with
    `app.normalize.models.ObservationStatus`.
    """

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    STOPPED = "stopped"
    DRAFT = "draft"
    UNKNOWN = "unknown"
    ENTERED_IN_ERROR = "entered_in_error"


_STATUS_MAP: dict[str, MedicationOrderStatus] = {
    "active": MedicationOrderStatus.ACTIVE,
    "on-hold": MedicationOrderStatus.ON_HOLD,
    "cancelled": MedicationOrderStatus.CANCELLED,
    "completed": MedicationOrderStatus.COMPLETED,
    "stopped": MedicationOrderStatus.STOPPED,
    "draft": MedicationOrderStatus.DRAFT,
    "unknown": MedicationOrderStatus.UNKNOWN,
    "entered-in-error": MedicationOrderStatus.ENTERED_IN_ERROR,
}


class NormalizedMedicationOrder(BaseModel):
    """A normalized `MedicationRequest` (an order, not an adherence record).

    `is_active_order` (True iff `status == active`) means a prescriber's
    order is currently active -- it is NOT proof the patient ever ingested
    the medication or is currently adherent (spec §31: order != adherence).
    This model has NO `is_taking` / adherence field of any kind, and none
    should ever be added to it: adherence is not something a
    `MedicationRequest` can tell you.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    medication_code: str | None
    medication_display: str | None
    code_system: str | None
    status: MedicationOrderStatus
    authored_on: ClinicalInstant
    intent: str | None

    @property
    def is_active_order(self) -> bool:
        """True iff `status == active`. NOT evidence of ingestion/adherence."""
        return self.status == MedicationOrderStatus.ACTIVE


def normalize_medication_order(resource: dict[str, Any]) -> NormalizedMedicationOrder:
    """Normalize a raw FHIR `MedicationRequest` resource dict."""
    medication_code: str | None = None
    code_system: str | None = None
    medication_display: str | None = None

    med_cc = resource.get("medicationCodeableConcept")
    if med_cc:
        codings = med_cc.get("coding") or []
        if codings:
            medication_code = codings[0].get("code")
            code_system = codings[0].get("system")
            medication_display = codings[0].get("display") or med_cc.get("text")
        else:
            medication_display = med_cc.get("text")
    else:
        med_ref = resource.get("medicationReference")
        if med_ref:
            medication_display = med_ref.get("display")

    raw_status = resource.get("status")
    status = (
        _STATUS_MAP.get(raw_status, MedicationOrderStatus.UNKNOWN)
        if isinstance(raw_status, str)
        else MedicationOrderStatus.UNKNOWN
    )

    authored_raw = resource.get("authoredOn")
    authored_on = parse_fhir_datetime(authored_raw) if authored_raw else absent_instant()

    return NormalizedMedicationOrder(
        id=resource.get("id") or "",
        medication_code=medication_code,
        medication_display=medication_display,
        code_system=code_system,
        status=status,
        authored_on=authored_on,
        intent=resource.get("intent"),
    )
