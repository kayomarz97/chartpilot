"""Concrete derived-metric registrations for the ClinicalValidityEngine.

Registers three metrics from unrelated clinical domains (renal function,
electrolyte correction, acid-base) to prove the engine's contract/evaluator
shape is generic rather than bespoke-per-metric. Each evaluator is
responsible for its OWN preconditions/limitations beyond "inputs present" --
the engine itself only gates on `required_inputs`.

Decimal-at-the-boundary note: clinical inputs and outputs are `Decimal`
throughout this module. The eGFR formula's fractional exponents (`α`,
`-1.200`, `0.9938**age`) have no exact `Decimal` power operator in the
standard library, so those specific operations are done in `float` and the
final result is immediately wrapped back into a `Decimal`, quantized to one
decimal place. No other arithmetic in this module leaves `Decimal`.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.validation.engine import ClinicalValidityEngine
from app.validation.models import ValidityContract, ValidityResult, ValidityStatus

# ---------------------------------------------------------------------------
# eGFR (CKD-EPI 2021, race-free, creatinine-based)
# ---------------------------------------------------------------------------

EGFR_METRIC_ID = "egfr_ckd_epi_2021_cr"

_EGFR_CONTRACT = ValidityContract(
    metric_id=EGFR_METRIC_ID,
    version="CKD-EPI 2021 creatinine",
    required_inputs=("age_years", "sex", "serum_creatinine_mg_dl"),
    required_units={"serum_creatinine_mg_dl": "mg/dL"},
    formula_or_method=(
        "eGFR = 142 * min(Scr/kappa,1)**alpha * max(Scr/kappa,1)**(-1.200) "
        "* 0.9938**Age * (1.012 if female else 1.0); kappa=0.7(F)/0.9(M), "
        "alpha=-0.241(F)/-0.302(M)"
    ),
    supporting_sources=(
        "Inker LA et al., 'New Creatinine- and Cystatin C-Based Equations "
        "to Estimate GFR without Race', N Engl J Med 2021;385:1737-1749.",
    ),
    effective_date="2021-01-01",
)

_STEADY_STATE_THRESHOLD = Decimal("0.20")


def _steady_state_limitation(creatinine_series: list[Decimal] | None) -> str | None:
    """Return a limitation string iff the series is NOT in steady state.

    "Not in steady state" is defined here as: the relative change between
    the minimum and maximum of the series (relative to the minimum) exceeds
    20%. A `None` or single-value series is treated as stable (no basis to
    call it unstable).
    """
    if creatinine_series is None or len(creatinine_series) < 2:
        return None
    lo = min(creatinine_series)
    hi = max(creatinine_series)
    if lo <= 0:
        return None
    relative_change = (hi - lo) / lo
    if relative_change > _STEADY_STATE_THRESHOLD:
        return "creatinine not in steady state (Δ>20%); eGFR unreliable -- show creatinine trend"
    return None


def _evaluate_egfr(inputs: Mapping[str, Any]) -> ValidityResult:
    age_years = Decimal(str(inputs["age_years"]))
    sex_raw = inputs["sex"]
    sex: Literal["male", "female"]
    if sex_raw not in ("male", "female"):
        return ValidityResult(
            metric_id=EGFR_METRIC_ID,
            version=_EGFR_CONTRACT.version,
            status=ValidityStatus.INVALID,
            value=None,
            unit=None,
            failed_preconditions=("sex",),
            limitations=(),
            detail=f"sex must be 'male' or 'female', got {sex_raw!r}",
        )
    sex = sex_raw
    scr = inputs["serum_creatinine_mg_dl"]
    scr = scr if isinstance(scr, Decimal) else Decimal(str(scr))

    if scr <= 0 or age_years <= 0:
        return ValidityResult(
            metric_id=EGFR_METRIC_ID,
            version=_EGFR_CONTRACT.version,
            status=ValidityStatus.INVALID,
            value=None,
            unit=None,
            failed_preconditions=(),
            limitations=(),
            detail="serum creatinine and age must be positive",
        )

    kappa = Decimal("0.7") if sex == "female" else Decimal("0.9")
    alpha = Decimal("-0.241") if sex == "female" else Decimal("-0.302")

    # Fractional powers: float-boundary math, documented at module level.
    ratio = float(scr / kappa)
    min_ratio_pow = min(ratio, 1.0) ** float(alpha)
    max_ratio_pow = max(ratio, 1.0) ** (-1.200)
    age_term = 0.9938 ** float(age_years)
    sex_term = 1.012 if sex == "female" else 1.0

    egfr_float = 142.0 * min_ratio_pow * max_ratio_pow * age_term * sex_term
    egfr = Decimal(str(egfr_float)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    creatinine_series = inputs.get("creatinine_series")
    limitation = _steady_state_limitation(creatinine_series)

    if limitation is not None:
        return ValidityResult(
            metric_id=EGFR_METRIC_ID,
            version=_EGFR_CONTRACT.version,
            status=ValidityStatus.VALID_WITH_LIMITATIONS,
            value=egfr,
            unit="mL/min/1.73m2",
            failed_preconditions=(),
            limitations=(limitation,),
            detail=None,
        )

    return ValidityResult(
        metric_id=EGFR_METRIC_ID,
        version=_EGFR_CONTRACT.version,
        status=ValidityStatus.VALID,
        value=egfr,
        unit="mL/min/1.73m2",
        failed_preconditions=(),
        limitations=(),
        detail=None,
    )


# ---------------------------------------------------------------------------
# Corrected calcium (Payne 1973)
# ---------------------------------------------------------------------------

CORRECTED_CALCIUM_METRIC_ID = "corrected_calcium"

_CORRECTED_CALCIUM_CONTRACT = ValidityContract(
    metric_id=CORRECTED_CALCIUM_METRIC_ID,
    version="Payne 1973",
    required_inputs=("calcium_mg_dl", "albumin_g_dl"),
    required_units={"calcium_mg_dl": "mg/dL", "albumin_g_dl": "g/dL"},
    formula_or_method="corrected = calcium + 0.8*(4.0 - albumin)",
    supporting_sources=(
        "Payne RB et al., 'Interpretation of serum calcium in patients with "
        "abnormal serum proteins', Br Med J 1973;4:643-646.",
    ),
    effective_date="1973-01-01",
)


def _evaluate_corrected_calcium(inputs: Mapping[str, Any]) -> ValidityResult:
    calcium = inputs["calcium_mg_dl"]
    calcium = calcium if isinstance(calcium, Decimal) else Decimal(str(calcium))
    albumin = inputs["albumin_g_dl"]
    albumin = albumin if isinstance(albumin, Decimal) else Decimal(str(albumin))

    corrected = calcium + Decimal("0.8") * (Decimal("4.0") - albumin)
    return ValidityResult(
        metric_id=CORRECTED_CALCIUM_METRIC_ID,
        version=_CORRECTED_CALCIUM_CONTRACT.version,
        status=ValidityStatus.VALID,
        value=corrected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        unit="mg/dL",
        failed_preconditions=(),
        limitations=(),
        detail=None,
    )


# ---------------------------------------------------------------------------
# Anion gap
# ---------------------------------------------------------------------------

ANION_GAP_METRIC_ID = "anion_gap"

_ANION_GAP_CONTRACT = ValidityContract(
    metric_id=ANION_GAP_METRIC_ID,
    version="Na-(Cl+HCO3)",
    required_inputs=("sodium_mmol_l", "chloride_mmol_l", "bicarbonate_mmol_l"),
    required_units={
        "sodium_mmol_l": "mmol/L",
        "chloride_mmol_l": "mmol/L",
        "bicarbonate_mmol_l": "mmol/L",
    },
    formula_or_method="anion_gap = Na - (Cl + HCO3)",
    supporting_sources=("Standard clinical chemistry anion gap formula.",),
    effective_date="1970-01-01",
)


def _evaluate_anion_gap(inputs: Mapping[str, Any]) -> ValidityResult:
    sodium = inputs["sodium_mmol_l"]
    sodium = sodium if isinstance(sodium, Decimal) else Decimal(str(sodium))
    chloride = inputs["chloride_mmol_l"]
    chloride = chloride if isinstance(chloride, Decimal) else Decimal(str(chloride))
    bicarbonate = inputs["bicarbonate_mmol_l"]
    bicarbonate = bicarbonate if isinstance(bicarbonate, Decimal) else Decimal(str(bicarbonate))

    gap = sodium - (chloride + bicarbonate)
    return ValidityResult(
        metric_id=ANION_GAP_METRIC_ID,
        version=_ANION_GAP_CONTRACT.version,
        status=ValidityStatus.VALID,
        value=gap.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        unit="mmol/L",
        failed_preconditions=(),
        limitations=(),
        detail=None,
    )


def build_default_engine() -> ClinicalValidityEngine:
    """Build a `ClinicalValidityEngine` with all three metrics registered."""
    engine = ClinicalValidityEngine()
    engine.register(_EGFR_CONTRACT, _evaluate_egfr)
    engine.register(_CORRECTED_CALCIUM_CONTRACT, _evaluate_corrected_calcium)
    engine.register(_ANION_GAP_CONTRACT, _evaluate_anion_gap)
    return engine
