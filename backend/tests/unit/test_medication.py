"""Unit tests for app.normalize.medication.normalize_medication_order.

Verifies status mapping (including hyphenated FHIR codes), medicationCode-
ableConcept coding + text handling, and -- the critical invariant -- that
the model never exposes any adherence/ingestion field: an active order
means a prescriber ordered it, not that the patient is taking it.
"""

from __future__ import annotations

from app.normalize.medication import MedicationOrderStatus, normalize_medication_order


def test_active_order_is_active_but_exposes_no_adherence_field() -> None:
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "1049221",
                    "display": "Amlodipine 5mg",
                }
            ]
        },
        "authoredOn": "2025-01-01T09:00:00Z",
    }
    order = normalize_medication_order(resource)

    assert order.status == MedicationOrderStatus.ACTIVE
    assert order.is_active_order is True
    assert order.medication_code == "1049221"
    assert order.medication_display == "Amlodipine 5mg"
    assert order.code_system == "http://www.nlm.nih.gov/research/umls/rxnorm"
    assert order.intent == "order"

    # Root requirement: an active order is NOT proof of ingestion/adherence
    # (spec §31) -- no such field may ever exist on this model.
    for forbidden in ("is_taking", "adherence", "is_adherent", "taking"):
        assert not hasattr(order, forbidden)


def test_stopped_order_is_not_active() -> None:
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr2",
        "status": "stopped",
        "medicationCodeableConcept": {"text": "Metformin"},
    }
    order = normalize_medication_order(resource)
    assert order.status == MedicationOrderStatus.STOPPED
    assert order.is_active_order is False
    assert order.medication_display == "Metformin"


def test_hyphenated_statuses_mapped() -> None:
    on_hold = normalize_medication_order(
        {"resourceType": "MedicationRequest", "id": "mr3", "status": "on-hold"}
    )
    assert on_hold.status == MedicationOrderStatus.ON_HOLD

    error = normalize_medication_order(
        {"resourceType": "MedicationRequest", "id": "mr4", "status": "entered-in-error"}
    )
    assert error.status == MedicationOrderStatus.ENTERED_IN_ERROR
    assert error.is_active_order is False


def test_medication_reference_display_fallback() -> None:
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr5",
        "status": "active",
        "medicationReference": {"display": "Custom Compound"},
    }
    order = normalize_medication_order(resource)
    assert order.medication_display == "Custom Compound"
    assert order.medication_code is None


def test_unknown_status_maps_to_unknown() -> None:
    order = normalize_medication_order(
        {"resourceType": "MedicationRequest", "id": "mr6", "status": "some-future-code"}
    )
    assert order.status == MedicationOrderStatus.UNKNOWN
