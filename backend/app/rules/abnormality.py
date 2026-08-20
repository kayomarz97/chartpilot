"""§29 abnormality precedence.

Given a `NormalizedObservation`, decide whether its value is abnormal and on
what basis, using a strict precedence order:

  1. A usable `reference_range` on the observation itself (a source-provided
     low/high) always wins when present.
  2. Failing that, a structured `interpretation` code (H/HH/L/LL/A) is used.
  3. Failing that, an operator-configured demo threshold may be used, but
     only as a last resort -- and it is clearly labelled as such
     (`CONFIGURED_DEMO_THRESHOLD`) so nothing downstream mistakes a demo
     knob for a clinically-sourced range.
  4. If none apply, the value's abnormality cannot be assessed at all.

Only a `NormalizedQuantity` value (i.e. one with a `Decimal .value`) can be
assessed numerically; a string value falls straight to basis NONE unless an
interpretation code is present.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.normalize.models import AbnormalityBasis, NormalizedObservation
from app.normalize.units import NormalizedQuantity
from app.rules.models import AbnormalityAssessment

_HIGH_CODES = frozenset({"H", "HH"})
_LOW_CODES = frozenset({"L", "LL"})
_ABNORMAL_CODES = frozenset({"A"})


def _usable_range(
    obs: NormalizedObservation,
) -> tuple[NormalizedQuantity | None, NormalizedQuantity | None] | None:
    """Return the first (low, high) reference range usable for comparison.

    Usable means at least one bound is present, and if both are present
    `low < high`. Returns `None` if no range on the observation qualifies.
    """
    for rr in obs.reference_ranges:
        if rr.low is None and rr.high is None:
            continue
        if rr.low is not None and rr.high is not None and rr.low.value >= rr.high.value:
            continue
        return (rr.low, rr.high)
    return None


def _direction_from_bounds(
    value: Decimal, low: Decimal | None, high: Decimal | None
) -> Literal["high", "low", "normal"]:
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "normal"


def _direction_from_interpretation(codes: list[str]) -> Literal["high", "low", "unknown"]:
    code_set = set(codes)
    if code_set & _HIGH_CODES:
        return "high"
    if code_set & _LOW_CODES:
        return "low"
    return "unknown"


def assess_abnormality(
    obs: NormalizedObservation,
    *,
    configured_low: Decimal | None = None,
    configured_high: Decimal | None = None,
) -> AbnormalityAssessment:
    """Apply the §29 abnormality precedence to `obs`."""
    numeric_value: Decimal | None = (
        obs.value.value if isinstance(obs.value, NormalizedQuantity) else None
    )

    # Precedence 1: a usable reference range on the observation.
    usable = _usable_range(obs)
    if usable is not None and numeric_value is not None:
        low, high = usable
        direction = _direction_from_bounds(
            numeric_value,
            low.value if low is not None else None,
            high.value if high is not None else None,
        )
        return AbnormalityAssessment(
            is_abnormal=direction != "normal",
            direction=direction,
            basis=AbnormalityBasis.REFERENCE_RANGE,
            detail=f"value {numeric_value} vs reference range low={low}, high={high}",
        )

    # Precedence 2: structured interpretation codes.
    if obs.interpretation:
        code_set = set(obs.interpretation)
        if code_set & (_HIGH_CODES | _LOW_CODES | _ABNORMAL_CODES):
            interpretation_direction = _direction_from_interpretation(obs.interpretation)
            return AbnormalityAssessment(
                is_abnormal=True,
                direction=interpretation_direction,
                basis=AbnormalityBasis.INTERPRETATION,
                detail=f"interpretation codes {sorted(code_set)}",
            )

    # Precedence 3: operator-configured demo threshold, last resort only.
    if numeric_value is not None and (configured_low is not None or configured_high is not None):
        direction = _direction_from_bounds(numeric_value, configured_low, configured_high)
        return AbnormalityAssessment(
            is_abnormal=direction != "normal",
            direction=direction,
            basis=AbnormalityBasis.CONFIGURED_DEMO_THRESHOLD,
            detail=(
                f"value {numeric_value} vs configured demo threshold "
                f"low={configured_low}, high={configured_high}"
            ),
        )

    return AbnormalityAssessment(
        is_abnormal=False,
        direction="unknown",
        basis=AbnormalityBasis.NONE,
        detail="no reference range, interpretation code, or configured threshold available",
    )
