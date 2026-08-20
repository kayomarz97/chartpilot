"""Unit tests for app.normalize.units.

Verifies analyte-aware UCUM conversion: potassium mmol/L <-> mEq/L (1:1),
creatinine mg/dL <-> umol/L (factor 88.42), and that an unknown/incompatible
unit raises rather than silently guessing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.normalize.errors import UnitNormalizationError
from app.normalize.units import normalize_quantity


def test_potassium_mmol_and_meq_are_numerically_equal() -> None:
    mmol = normalize_quantity("potassium", Decimal("4.0"), "mmol/L")
    meq = normalize_quantity("potassium", Decimal("4.0"), "mEq/L")
    assert mmol.unit == "mmol/L"
    assert meq.unit == "mmol/L"
    assert mmol.value == meq.value == Decimal("4.0")


def test_potassium_unit_spelling_is_case_and_unicode_insensitive() -> None:
    result = normalize_quantity("potassium", "4.0", "MEQ/L")
    assert result.value == Decimal("4.0")
    assert result.unit == "mmol/L"


def test_creatinine_canonical_unit_is_mg_dl_passthrough() -> None:
    # Canonical unit for creatinine is mg/dL (documented in units.py); a
    # value already in mg/dL passes through unchanged.
    result = normalize_quantity("creatinine", Decimal("1.0"), "mg/dL")
    assert result.unit == "mg/dL"
    assert result.value == Decimal("1.0")
    assert result.original_value == Decimal("1.0")
    assert result.original_unit == "mg/dL"


def test_creatinine_umol_converts_to_mg_dl_via_88_42_factor() -> None:
    # umol/L = mg/dL * 88.42  =>  1.0 mg/dL corresponds to 88.42 umol/L.
    # Feeding 88.42 umol/L back in must normalize to ~1.0 mg/dL.
    result = normalize_quantity("creatinine", Decimal("88.42"), "umol/L")
    assert result.unit == "mg/dL"
    assert abs(result.value - Decimal("1.0")) < Decimal("0.0001")


def test_creatinine_umol_unicode_micro_sign_accepted() -> None:
    result = normalize_quantity("creatinine", Decimal("88.42"), "µmol/L")
    assert result.unit == "mg/dL"
    assert abs(result.value - Decimal("1.0")) < Decimal("0.0001")


def test_sodium_mmol_and_meq_are_numerically_equal() -> None:
    mmol = normalize_quantity("sodium", Decimal("140"), "mmol/L")
    meq = normalize_quantity("sodium", Decimal("140"), "mEq/L")
    assert mmol.value == meq.value == Decimal("140")


def test_unknown_unit_for_known_analyte_raises() -> None:
    with pytest.raises(UnitNormalizationError):
        normalize_quantity("potassium", Decimal("4.0"), "g/L")


def test_unknown_analyte_raises() -> None:
    with pytest.raises(UnitNormalizationError):
        normalize_quantity("glucose", Decimal("100"), "mg/dL")


def test_invalid_numeric_value_raises() -> None:
    with pytest.raises(UnitNormalizationError):
        normalize_quantity("potassium", "not-a-number", "mmol/L")
