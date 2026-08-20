"""Analyte-aware UCUM quantity normalization.

Lab values arrive in whatever unit the source system used (`mmol/L` vs
`mEq/L`, `mg/dL` vs `umol/L`, ...). Comparing raw values across sources
without converting to a single canonical unit per analyte silently produces
nonsense (e.g. treating a creatinine of 88 as eight-fold above a creatinine
of 11 when one is `umol/L` and the other `mg/dL`). This module holds a small,
explicit conversion registry and normalizes every quantity to a fixed
canonical unit for its analyte -- or raises rather than guessing when the
unit is unknown or has no defined conversion.

All arithmetic uses `decimal.Decimal`, never `float`, so clinical values are
never subject to binary floating-point rounding error.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

from app.normalize.errors import UnitNormalizationError


class NormalizedQuantity(BaseModel):
    """A quantity converted to its analyte's canonical unit.

    `original_value` / `original_unit` are preserved unchanged so the raw
    source value is always recoverable, even after conversion.
    """

    model_config = ConfigDict(frozen=True)

    value: Decimal
    unit: str
    original_value: Decimal
    original_unit: str


# Conversion registry: analyte name (lowercased) -> (canonical unit,
# {normalized unit spelling -> multiplicative factor to canonical}).
#
# Canonical unit choices are deliberate and documented here so they never
# drift silently:
#   - potassium, sodium: canonical `mmol/L`. Both are monovalent ions, so
#     `mEq/L` (milliequivalents/L) converts 1:1 to `mmol/L`.
#   - creatinine: canonical `mg/dL`. `umol/L` converts via the standard
#     clinical factor `umol/L = mg/dL * 88.42`, i.e. `mg/dL = umol/L / 88.42`.
_CREATININE_FACTOR = Decimal("88.42")

_REGISTRY: dict[str, tuple[str, dict[str, Decimal]]] = {
    "potassium": (
        "mmol/L",
        {"mmol/l": Decimal("1"), "meq/l": Decimal("1")},
    ),
    "sodium": (
        "mmol/L",
        {"mmol/l": Decimal("1"), "meq/l": Decimal("1")},
    ),
    "creatinine": (
        "mg/dL",
        {"mg/dl": Decimal("1"), "umol/l": Decimal("1") / _CREATININE_FACTOR},
    ),
}


def _canonicalize_unit_spelling(unit: str) -> str:
    """Fold common UCUM spelling variants to one lookup key.

    Handles unicode micro-sign variants (`µ`/`μ` -> `u`), case, and
    whitespace so `umol/L`, `UMOL/L`, and `µmol/L` all resolve identically.
    """
    folded = unit.strip().replace("µ", "u").replace("μ", "u")
    return folded.lower()


def normalize_quantity(analyte: str, value: Decimal | float | str, unit: str) -> NormalizedQuantity:
    """Convert `value unit` for `analyte` to that analyte's canonical unit.

    Raises:
        UnitNormalizationError: `analyte` has no registered conversions,
            `unit` is not known/convertible for that analyte, or `value`
            cannot be parsed as a decimal number.
    """
    try:
        original_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise UnitNormalizationError(f"invalid numeric quantity value: {value!r}") from exc

    analyte_key = analyte.strip().lower()
    entry = _REGISTRY.get(analyte_key)
    if entry is None:
        raise UnitNormalizationError(f"no unit conversion registry for analyte {analyte!r}")

    canonical_unit, conversions = entry
    factor = conversions.get(_canonicalize_unit_spelling(unit))
    if factor is None:
        raise UnitNormalizationError(
            f"unit {unit!r} is not a known/convertible unit for analyte {analyte!r}"
        )

    return NormalizedQuantity(
        value=original_value * factor,
        unit=canonical_unit,
        original_value=original_value,
        original_unit=unit,
    )
