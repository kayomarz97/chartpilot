"""K_HIGH_RISK_001: critical hyperkalemia on a potassium-raising medication.

A demo safety rule, not universal clinical policy (see `data/rules.toml`).
Fires only when every one of the following holds:

  1. A current (latest-valid, entered-in-error/cancelled excluded) potassium
     observation exists, is a `NormalizedQuantity` already normalized to
     `mmol/L` (never on an unconverted/unknown unit), and has a
     determinable `effective` time.
  2. That value is at or above the configured critical band.
  3. §29 abnormality assessment agrees the value is abnormal -- except the
     §29.2 conflict case: if the observation's OWN reference range calls the
     value normal while the configured critical band disagrees, the rule
     does NOT silently fire; it reports `REQUIRES_REVIEW` with both bases on
     record instead.
  4. At least one currently-active order is on a potassium-raising
     medication class (per the versioned medication-class artifact).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.normalize.medication import NormalizedMedicationOrder
from app.normalize.models import AbnormalityBasis, NormalizedObservation
from app.normalize.observation import latest_valid_observation
from app.normalize.temporal import Ordering, Precision, compare
from app.normalize.units import NormalizedQuantity
from app.rules.abnormality import assess_abnormality
from app.rules.medication_classes import MedicationClasses, load_medication_classes
from app.rules.models import RuleResult, RuleVerdict, Severity

RULE_ID = "K_HIGH_RISK_001"

_POTASSIUM_LOINC_CODES = ("2823-3", "6298-4")
_CANONICAL_UNIT = "mmol/L"

_DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "rules.toml"


@dataclass(frozen=True)
class KHighRiskConfig:
    """The loaded `[k_high_risk_001]` section of `data/rules.toml`."""

    version: str
    high_mmol_l: Decimal
    critical_mmol_l: Decimal


def load_k_high_risk_config(path: Path | None = None) -> KHighRiskConfig:
    """Load the K_HIGH_RISK_001 threshold config from `rules.toml`."""
    target = path if path is not None else _DEFAULT_RULES_PATH
    with target.open("rb") as fh:
        data = tomllib.load(fh)
    section = data["k_high_risk_001"]
    return KHighRiskConfig(
        version=str(section["version"]),
        high_mmol_l=Decimal(str(section["high_mmol_l"])),
        critical_mmol_l=Decimal(str(section["critical_mmol_l"])),
    )


def _latest_potassium(observations: list[NormalizedObservation]) -> NormalizedObservation | None:
    """Latest valid potassium observation across both known LOINC codes."""
    candidates = [
        obs
        for code in _POTASSIUM_LOINC_CODES
        if (obs := latest_valid_observation(observations, code=code)) is not None
    ]
    if not candidates:
        return None
    best = candidates[0]
    for obs in candidates[1:]:
        if compare(obs.effective, best.effective) == Ordering.AFTER:
            best = obs
    return best


def _effective_time_str(obs: NormalizedObservation) -> str:
    if obs.effective.source_string is not None:
        return obs.effective.source_string
    if obs.effective.value_utc is not None:
        return obs.effective.value_utc.isoformat()
    return ""


def _not_fired(
    *,
    version: str,
    verdict: RuleVerdict,
    rationale: str,
    evaluated_at: datetime,
    matched_observation_ids: tuple[str, ...] = (),
    normalized_values: dict[str, str] | None = None,
    abnormality_basis: AbnormalityBasis = AbnormalityBasis.NONE,
    matched_effective_times: tuple[str, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=RULE_ID,
        rule_version=version,
        verdict=verdict,
        severity=None,
        matched_observation_ids=matched_observation_ids,
        matched_medication_ids=(),
        normalized_values=normalized_values or {},
        abnormality_basis=abnormality_basis,
        matched_effective_times=matched_effective_times,
        rationale=rationale,
        evaluated_at=evaluated_at,
    )


def evaluate_k_high_risk(
    observations: list[NormalizedObservation],
    medications: list[NormalizedMedicationOrder],
    *,
    config: KHighRiskConfig | None = None,
    med_classes: MedicationClasses | None = None,
    evaluated_at: datetime,
) -> RuleResult:
    """Evaluate K_HIGH_RISK_001 against a patient's observations/medications."""
    cfg = config if config is not None else load_k_high_risk_config()
    classes = med_classes if med_classes is not None else load_medication_classes()

    obs = _latest_potassium(observations)
    if obs is None:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.INSUFFICIENT_DATA,
            rationale="no valid potassium observation found",
            evaluated_at=evaluated_at,
        )

    if not isinstance(obs.value, NormalizedQuantity) or obs.value.unit != _CANONICAL_UNIT:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.INSUFFICIENT_DATA,
            rationale="potassium unit not safely normalized",
            evaluated_at=evaluated_at,
            matched_observation_ids=(obs.id,),
        )

    if obs.effective.precision == Precision.ABSENT:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.INSUFFICIENT_DATA,
            rationale="potassium observation has no determinable effective time",
            evaluated_at=evaluated_at,
            matched_observation_ids=(obs.id,),
        )

    value = obs.value.value
    normalized_values = {"potassium_mmol_l": str(value)}
    assessment = assess_abnormality(obs, configured_low=None, configured_high=cfg.high_mmol_l)

    above_critical = value >= cfg.critical_mmol_l

    if not above_critical:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.NOT_FIRED,
            rationale=(
                f"potassium {value} mmol/L is below the critical band ({cfg.critical_mmol_l})"
            ),
            evaluated_at=evaluated_at,
            matched_observation_ids=(obs.id,),
            normalized_values=normalized_values,
            abnormality_basis=assessment.basis,
            matched_effective_times=(_effective_time_str(obs),),
        )

    # §29.2 conflict: the observation's own reference range says normal, but
    # the configured critical band disagrees -- never silently fire.
    if assessment.basis == AbnormalityBasis.REFERENCE_RANGE and not assessment.is_abnormal:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.REQUIRES_REVIEW,
            rationale=(
                f"potassium {value} mmol/L is at/above the configured critical band "
                f"({cfg.critical_mmol_l}) but the observation's own reference range "
                f"reports it as normal ({assessment.detail}); requires clinician review"
            ),
            evaluated_at=evaluated_at,
            matched_observation_ids=(obs.id,),
            normalized_values=normalized_values,
            abnormality_basis=assessment.basis,
            matched_effective_times=(_effective_time_str(obs),),
        )

    if not assessment.is_abnormal:
        return _not_fired(
            version=cfg.version,
            verdict=RuleVerdict.NOT_FIRED,
            rationale=f"potassium {value} mmol/L not established as abnormal ({assessment.detail})",
            evaluated_at=evaluated_at,
            matched_observation_ids=(obs.id,),
            normalized_values=normalized_values,
            abnormality_basis=assessment.basis,
            matched_effective_times=(_effective_time_str(obs),),
        )

    matched_medication_ids: list[str] = []
    for order in medications:
        if not order.is_active_order:
            continue
        matched, ingredient, med_class = classes.is_potassium_raising(order)
        if matched:
            matched_medication_ids.append(order.id)

    if not matched_medication_ids:
        return RuleResult(
            rule_id=RULE_ID,
            rule_version=cfg.version,
            verdict=RuleVerdict.NOT_FIRED,
            severity=None,
            matched_observation_ids=(obs.id,),
            matched_medication_ids=(),
            normalized_values=normalized_values,
            abnormality_basis=assessment.basis,
            matched_effective_times=(_effective_time_str(obs),),
            rationale=(
                f"potassium {value} mmol/L is at/above the critical band and abnormal, "
                "but no active potassium-raising medication order found"
            ),
            evaluated_at=evaluated_at,
        )

    return RuleResult(
        rule_id=RULE_ID,
        rule_version=cfg.version,
        verdict=RuleVerdict.FIRED,
        severity=Severity.CRITICAL,
        matched_observation_ids=(obs.id,),
        matched_medication_ids=tuple(matched_medication_ids),
        normalized_values=normalized_values,
        abnormality_basis=assessment.basis,
        matched_effective_times=(_effective_time_str(obs),),
        rationale=(
            f"critical hyperkalemia: potassium {value} mmol/L (>= critical band "
            f"{cfg.critical_mmol_l}), abnormality basis={assessment.basis.value}, "
            f"on {len(matched_medication_ids)} active potassium-raising medication order(s)"
        ),
        evaluated_at=evaluated_at,
    )
