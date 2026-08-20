"""Unit tests for app.normalize.observation.latest_valid_observation.

Verifies retracted statuses (entered-in-error, cancelled) are excluded
unconditionally, a later `corrected` value supersedes an earlier `final`,
and tie-breaking (same instant, or precision-mismatched INDETERMINATE_ORDER)
falls back to status precedence then `issued`.
"""

from __future__ import annotations

from typing import Any

from app.normalize.models import ObservationStatus
from app.normalize.observation import latest_valid_observation, normalize_observation


def _potassium(
    id_: str, status: str, value: float, effective: str, issued: str | None = None
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": id_,
        "status": status,
        "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
        "valueQuantity": {"value": value, "unit": "mmol/L"},
        "effectiveDateTime": effective,
    }
    if issued:
        resource["issued"] = issued
    return resource


def test_entered_in_error_excluded() -> None:
    good = normalize_observation(_potassium("k1", "final", 4.0, "2025-01-01T10:00:00Z"))
    bad = normalize_observation(_potassium("k2", "entered-in-error", 9.9, "2025-01-02T10:00:00Z"))

    latest = latest_valid_observation([good, bad], code="2823-3")
    assert latest is not None
    assert latest.id == "k1"


def test_cancelled_excluded() -> None:
    good = normalize_observation(_potassium("k1", "final", 4.0, "2025-01-01T10:00:00Z"))
    cancelled = normalize_observation(_potassium("k2", "cancelled", 9.9, "2025-01-02T10:00:00Z"))

    latest = latest_valid_observation([good, cancelled], code="2823-3")
    assert latest is not None
    assert latest.id == "k1"


def test_corrected_supersedes_earlier_final() -> None:
    final = normalize_observation(_potassium("k1", "final", 4.0, "2025-01-01T10:00:00Z"))
    corrected = normalize_observation(_potassium("k2", "corrected", 4.5, "2025-01-02T10:00:00Z"))

    latest = latest_valid_observation([final, corrected], code="2823-3")
    assert latest is not None
    assert latest.id == "k2"
    assert latest.status == ObservationStatus.CORRECTED


def test_retracted_value_never_returned_even_as_only_candidate() -> None:
    only = normalize_observation(_potassium("k1", "entered-in-error", 9.9, "2025-01-01T10:00:00Z"))
    assert latest_valid_observation([only], code="2823-3") is None


def test_no_matching_code_returns_none() -> None:
    obs = normalize_observation(_potassium("k1", "final", 4.0, "2025-01-01T10:00:00Z"))
    assert latest_valid_observation([obs], code="9999-9") is None


def test_same_instant_prefers_corrected_over_final() -> None:
    final = normalize_observation(_potassium("k1", "final", 4.0, "2025-01-01T10:00:00Z"))
    corrected = normalize_observation(_potassium("k2", "corrected", 4.1, "2025-01-01T10:00:00Z"))

    latest = latest_valid_observation([final, corrected], code="2823-3")
    assert latest is not None
    assert latest.id == "k2"


def test_indeterminate_order_falls_back_to_issued() -> None:
    # 'effective' YEAR 2025 vs DAY 2025-06-15 is INDETERMINATE_ORDER --
    # neither has provable precedence, so the tie-break falls to `issued`.
    a = normalize_observation(_potassium("k1", "final", 4.0, "2025", issued="2025-01-01T10:00:00Z"))
    b = normalize_observation(
        _potassium("k2", "final", 4.5, "2025-06-15", issued="2025-06-16T10:00:00Z")
    )

    latest = latest_valid_observation([a, b], code="2823-3")
    assert latest is not None
    assert latest.id == "k2"
