"""Unit tests for app.rules.abnormality.assess_abnormality (spec §29).

Verifies the strict precedence order: a usable reference range beats
interpretation codes, interpretation codes beat a configured demo threshold,
and none of the above yields basis NONE.
"""

from __future__ import annotations

from decimal import Decimal

from app.normalize.models import AbnormalityBasis
from app.normalize.observation import normalize_observation
from app.rules.abnormality import assess_abnormality

_POTASSIUM_CODE = {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]}


def test_reference_range_present_beats_interpretation() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-1",
        "status": "final",
        "code": _POTASSIUM_CODE,
        "valueQuantity": {"value": 6.2, "unit": "mmol/L"},
        "referenceRange": [
            {"low": {"value": 3.5, "unit": "mmol/L"}, "high": {"value": 5.1, "unit": "mmol/L"}}
        ],
        # Contradictory interpretation code -- reference range must still win.
        "interpretation": [{"coding": [{"code": "N"}]}],
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)
    assessment = assess_abnormality(obs, configured_low=None, configured_high=None)

    assert assessment.basis == AbnormalityBasis.REFERENCE_RANGE
    assert assessment.is_abnormal is True
    assert assessment.direction == "high"


def test_no_range_but_interpretation_high() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-2",
        "status": "final",
        "code": _POTASSIUM_CODE,
        "valueQuantity": {"value": 6.2, "unit": "mmol/L"},
        "interpretation": [{"coding": [{"code": "H"}]}],
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)
    assessment = assess_abnormality(obs, configured_low=None, configured_high=None)

    assert assessment.basis == AbnormalityBasis.INTERPRETATION
    assert assessment.is_abnormal is True
    assert assessment.direction == "high"


def test_neither_range_nor_interpretation_uses_configured_threshold() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-3",
        "status": "final",
        "code": _POTASSIUM_CODE,
        "valueQuantity": {"value": 6.2, "unit": "mmol/L"},
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)
    assessment = assess_abnormality(obs, configured_low=None, configured_high=Decimal("5.5"))

    assert assessment.basis == AbnormalityBasis.CONFIGURED_DEMO_THRESHOLD
    assert assessment.is_abnormal is True
    assert assessment.direction == "high"


def test_none_of_the_above_yields_basis_none() -> None:
    resource = {
        "resourceType": "Observation",
        "id": "obs-4",
        "status": "final",
        "code": _POTASSIUM_CODE,
        "valueQuantity": {"value": 4.2, "unit": "mmol/L"},
        "effectiveDateTime": "2025-01-01T10:00:00Z",
    }
    obs = normalize_observation(resource)
    assessment = assess_abnormality(obs, configured_low=None, configured_high=None)

    assert assessment.basis == AbnormalityBasis.NONE
    assert assessment.is_abnormal is False
    assert assessment.direction == "unknown"
