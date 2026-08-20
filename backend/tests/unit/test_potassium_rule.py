"""Unit tests for app.rules.potassium.evaluate_k_high_risk (K_HIGH_RISK_001).

Covers the positive fire case, exclusion of entered-in-error values, refusal
to fire on an unsafely-normalized unit, a resolved (normal) potassium not
firing, and a critical potassium with no potassium-raising medication not
firing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.normalize.medication import normalize_medication_order
from app.normalize.models import AbnormalityBasis
from app.normalize.observation import normalize_observation
from app.rules.models import RuleVerdict, Severity
from app.rules.potassium import evaluate_k_high_risk

_NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _potassium(id_: str, status: str, value: float, unit: str = "mmol/L") -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": id_,
        "status": status,
        "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": "2025-05-30T10:00:00Z",
    }


def _lisinopril(id_: str, status: str = "active") -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "id": id_,
        "status": status,
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "29046",
                    "display": "Lisinopril 10mg Tab",
                }
            ]
        },
    }


def _amlodipine(id_: str, status: str = "active") -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "id": id_,
        "status": status,
        "medicationCodeableConcept": {"coding": [{"code": "1049221", "display": "Amlodipine 5mg"}]},
    }


def test_positive_fire_critical_potassium_on_lisinopril() -> None:
    obs = normalize_observation(_potassium("k1", "final", 6.2))
    med = normalize_medication_order(_lisinopril("m1"))

    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)

    assert result.verdict == RuleVerdict.FIRED
    assert result.severity == Severity.CRITICAL
    assert result.matched_observation_ids == ("k1",)
    assert result.matched_medication_ids == ("m1",)
    assert result.normalized_values["potassium_mmol_l"] == "6.2"
    assert result.abnormality_basis in (
        AbnormalityBasis.REFERENCE_RANGE,
        AbnormalityBasis.INTERPRETATION,
        AbnormalityBasis.CONFIGURED_DEMO_THRESHOLD,
    )
    assert result.rule_id == "K_HIGH_RISK_001"


def test_entered_in_error_potassium_does_not_fire() -> None:
    obs = normalize_observation(_potassium("k1", "entered-in-error", 6.2))
    med = normalize_medication_order(_lisinopril("m1"))

    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)

    assert result.verdict in (RuleVerdict.NOT_FIRED, RuleVerdict.INSUFFICIENT_DATA)


def test_unknown_unit_potassium_does_not_fire() -> None:
    # "banana" is not a registered unit for potassium, so normalize_observation
    # falls back to an unconverted passthrough quantity with unit "banana".
    obs = normalize_observation(_potassium("k1", "final", 6.2, unit="banana"))
    med = normalize_medication_order(_lisinopril("m1"))

    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)

    assert result.verdict == RuleVerdict.INSUFFICIENT_DATA


def test_resolved_normal_potassium_does_not_fire() -> None:
    obs = normalize_observation(_potassium("k1", "final", 4.1))
    med = normalize_medication_order(_lisinopril("m1"))

    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)

    assert result.verdict == RuleVerdict.NOT_FIRED


def test_critical_potassium_without_potassium_raising_medication_does_not_fire() -> None:
    obs = normalize_observation(_potassium("k1", "final", 6.2))
    med = normalize_medication_order(_amlodipine("m1"))

    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)

    assert result.verdict == RuleVerdict.NOT_FIRED
    assert result.matched_medication_ids == ()
