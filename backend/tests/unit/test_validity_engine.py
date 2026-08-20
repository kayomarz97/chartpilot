"""Unit tests for app.validation.engine.ClinicalValidityEngine.

Verifies the engine's generic contract: an unknown metric_id is
NOT_APPLICABLE, a metric with a missing required input is INSUFFICIENT_DATA
(and never returns a number), and a metric with all required inputs present
actually invokes its evaluator.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.validation.engine import ClinicalValidityEngine
from app.validation.models import ValidityContract, ValidityResult, ValidityStatus


def _make_engine() -> ClinicalValidityEngine:
    engine = ClinicalValidityEngine()
    contract = ValidityContract(
        metric_id="dummy_metric",
        version="1.0.0",
        required_inputs=("a", "b"),
        required_units={},
        formula_or_method="a + b",
        supporting_sources=(),
        effective_date="2020-01-01",
    )

    def evaluator(inputs: dict[str, Any]) -> ValidityResult:
        return ValidityResult(
            metric_id="dummy_metric",
            version="1.0.0",
            status=ValidityStatus.VALID,
            value=Decimal(inputs["a"]) + Decimal(inputs["b"]),
            unit=None,
            failed_preconditions=(),
            limitations=(),
            detail=None,
        )

    engine.register(contract, evaluator)
    return engine


def test_unknown_metric_id_is_not_applicable() -> None:
    engine = _make_engine()
    result = engine.evaluate("no_such_metric", {})
    assert result.status == ValidityStatus.NOT_APPLICABLE
    assert result.value is None


def test_missing_required_input_is_insufficient_data_and_returns_no_number() -> None:
    engine = _make_engine()
    result = engine.evaluate("dummy_metric", {"a": Decimal("1")})
    assert result.status == ValidityStatus.INSUFFICIENT_DATA
    assert result.value is None
    assert "b" in result.failed_preconditions


def test_present_inputs_invoke_the_evaluator() -> None:
    engine = _make_engine()
    result = engine.evaluate("dummy_metric", {"a": Decimal("1"), "b": Decimal("2")})
    assert result.status == ValidityStatus.VALID
    assert result.value == Decimal("3")
