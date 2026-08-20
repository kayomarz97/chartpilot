"""Unit tests for app.validation.metrics registrations.

Iterates all three registered metric_ids (eGFR, corrected calcium, anion
gap) through the SAME `ClinicalValidityEngine` to prove the engine is
generic across unrelated clinical domains, not bespoke per metric.
"""

from __future__ import annotations

from decimal import Decimal

from app.validation.metrics import (
    ANION_GAP_METRIC_ID,
    CORRECTED_CALCIUM_METRIC_ID,
    EGFR_METRIC_ID,
    build_default_engine,
)
from app.validation.models import ValidityStatus


def test_egfr_known_case_is_plausible() -> None:
    engine = build_default_engine()
    result = engine.evaluate(
        EGFR_METRIC_ID,
        {
            "age_years": 60,
            "sex": "male",
            "serum_creatinine_mg_dl": Decimal("1.2"),
        },
    )
    assert result.status == ValidityStatus.VALID
    assert result.value is not None
    assert Decimal("60") <= result.value <= Decimal("75")


def test_egfr_non_steady_state_creatinine_flags_limitation() -> None:
    engine = build_default_engine()
    result = engine.evaluate(
        EGFR_METRIC_ID,
        {
            "age_years": 60,
            "sex": "male",
            "serum_creatinine_mg_dl": Decimal("2.5"),
            "creatinine_series": [Decimal("1.0"), Decimal("2.5")],
        },
    )
    assert result.status == ValidityStatus.VALID_WITH_LIMITATIONS
    assert result.value is not None
    assert any("steady state" in limitation for limitation in result.limitations)


def test_egfr_stable_series_is_plain_valid() -> None:
    engine = build_default_engine()
    result = engine.evaluate(
        EGFR_METRIC_ID,
        {
            "age_years": 60,
            "sex": "male",
            "serum_creatinine_mg_dl": Decimal("1.2"),
            "creatinine_series": [Decimal("1.15"), Decimal("1.20"), Decimal("1.18")],
        },
    )
    assert result.status == ValidityStatus.VALID
    assert result.limitations == ()


def test_corrected_calcium_missing_albumin_is_insufficient_data() -> None:
    engine = build_default_engine()
    result = engine.evaluate(CORRECTED_CALCIUM_METRIC_ID, {"calcium_mg_dl": Decimal("7.5")})
    assert result.status == ValidityStatus.INSUFFICIENT_DATA
    assert result.value is None
    assert "albumin_g_dl" in result.failed_preconditions


def test_corrected_calcium_computes_with_albumin() -> None:
    engine = build_default_engine()
    result = engine.evaluate(
        CORRECTED_CALCIUM_METRIC_ID,
        {"calcium_mg_dl": Decimal("7.5"), "albumin_g_dl": Decimal("2.0")},
    )
    assert result.status == ValidityStatus.VALID
    # corrected = 7.5 + 0.8*(4.0 - 2.0) = 9.1
    assert result.value == Decimal("9.10")


def test_anion_gap_computes() -> None:
    engine = build_default_engine()
    result = engine.evaluate(
        ANION_GAP_METRIC_ID,
        {
            "sodium_mmol_l": Decimal("140"),
            "chloride_mmol_l": Decimal("100"),
            "bicarbonate_mmol_l": Decimal("24"),
        },
    )
    assert result.status == ValidityStatus.VALID
    assert result.value == Decimal("16.0")


def test_all_three_metrics_share_the_same_engine_instance() -> None:
    engine = build_default_engine()
    ids = [EGFR_METRIC_ID, CORRECTED_CALCIUM_METRIC_ID, ANION_GAP_METRIC_ID]
    inputs = [
        {"age_years": 60, "sex": "male", "serum_creatinine_mg_dl": Decimal("1.2")},
        {"calcium_mg_dl": Decimal("7.5"), "albumin_g_dl": Decimal("2.0")},
        {
            "sodium_mmol_l": Decimal("140"),
            "chloride_mmol_l": Decimal("100"),
            "bicarbonate_mmol_l": Decimal("24"),
        },
    ]
    for metric_id, metric_inputs in zip(ids, inputs, strict=True):
        result = engine.evaluate(metric_id, metric_inputs)
        assert result.status in (ValidityStatus.VALID, ValidityStatus.VALID_WITH_LIMITATIONS)
        assert result.value is not None
