"""Unit tests for app.normalize.observation.normalize_observation.

Verifies value[x] handling (valueQuantity/valueString), component
round-trip, dataAbsentReason, interpretation codes, referenceRange
low/high, notes never being trusted, and that an unconvertible unit warns
instead of crashing the whole observation.
"""

from __future__ import annotations

from decimal import Decimal

from app.normalize.observation import normalize_observation
from app.normalize.units import NormalizedQuantity


def _potassium_code() -> dict[str, object]:
    return {
        "coding": [{"system": "http://loinc.org", "code": "2823-3", "display": "Potassium"}],
        "text": "Potassium",
    }


def test_value_quantity_normalized_with_unit_conversion() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-k-1",
        "status": "final",
        "code": _potassium_code(),
        "valueQuantity": {"value": 4.2, "unit": "mEq/L"},
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)

    assert obs.code == "2823-3"
    assert obs.code_system == "http://loinc.org"
    assert isinstance(obs.value, NormalizedQuantity)
    assert obs.value.unit == "mmol/L"
    assert obs.value.value == Decimal("4.2")
    assert obs.normalization_warnings == []


def test_value_string_passthrough() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-str-1",
        "status": "final",
        "code": {"text": "Urine culture result"},
        "valueString": "No growth",
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)
    assert obs.value == "No growth"


def test_component_round_trip() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-bp-1",
        "status": "final",
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}
            ]
        },
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                "valueQuantity": {"value": 120, "unit": "mmHg"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                "valueQuantity": {"value": 80, "unit": "mmHg"},
            },
        ],
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)

    assert len(obs.components) == 2
    systolic, diastolic = obs.components
    assert systolic.code == "8480-6"
    assert isinstance(systolic.value, NormalizedQuantity)
    assert systolic.value.value == Decimal("120")
    assert systolic.value.unit == "mmHg"
    assert diastolic.code == "8462-4"
    assert isinstance(diastolic.value, NormalizedQuantity)
    assert diastolic.value.value == Decimal("80")


def test_data_absent_reason() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-dar-1",
        "status": "final",
        "code": _potassium_code(),
        "dataAbsentReason": {"coding": [{"code": "not-performed"}]},
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)
    assert obs.value is None
    assert obs.data_absent_reason == "not-performed"


def test_interpretation_codes_collected() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-interp-1",
        "status": "final",
        "code": _potassium_code(),
        "valueQuantity": {"value": 6.1, "unit": "mmol/L"},
        "interpretation": [{"coding": [{"code": "H", "display": "High"}]}],
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)
    assert obs.interpretation == ["H"]


def test_reference_range_low_high_normalized() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-rr-1",
        "status": "final",
        "code": _potassium_code(),
        "valueQuantity": {"value": 4.0, "unit": "mmol/L"},
        "referenceRange": [
            {
                "low": {"value": 3.5, "unit": "mmol/L"},
                "high": {"value": 5.1, "unit": "mmol/L"},
                "type": {"text": "Normal range"},
            }
        ],
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)

    assert len(obs.reference_ranges) == 1
    rr = obs.reference_ranges[0]
    assert rr.low is not None and rr.low.value == Decimal("3.5")
    assert rr.high is not None and rr.high.value == Decimal("5.1")
    assert rr.type_text == "Normal range"


def test_note_becomes_untrusted_narrative() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-note-1",
        "status": "final",
        "code": {"text": "General note"},
        "note": [{"text": "Patient reports fasting for 8 hours"}],
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)

    assert len(obs.notes) == 1
    assert obs.notes[0].text == "Patient reports fasting for 8 hours"
    assert obs.notes[0].trusted is False


def test_unconvertible_unit_warns_but_does_not_crash() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-badunit-1",
        "status": "final",
        "code": _potassium_code(),
        "valueQuantity": {"value": 4.0, "unit": "g/L"},
        "effectiveDateTime": "2025-01-01",
    }
    obs = normalize_observation(resource)

    assert isinstance(obs.value, NormalizedQuantity)
    assert obs.value.original_unit == "g/L"
    assert obs.value.value == Decimal("4.0")  # passthrough, unconverted
    assert len(obs.normalization_warnings) == 1
    assert "g/L" in obs.normalization_warnings[0]
