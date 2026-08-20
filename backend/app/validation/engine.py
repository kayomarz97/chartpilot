"""The generic ClinicalValidityEngine.

The engine's only job is bookkeeping shared by every derived metric: hold a
registry of (contract, evaluator) pairs, and refuse to call an evaluator at
all when a required input is missing (`INSUFFICIENT_DATA` -- never a
fabricated number). It must never contain metric-specific logic (formulas,
steady-state checks, ...); those live in each metric's evaluator, registered
via `register`. See `app.validation.metrics` for the concrete registrations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.validation.models import ValidityContract, ValidityResult, ValidityStatus

Evaluator = Callable[[Mapping[str, Any]], ValidityResult]


@dataclass(frozen=True)
class _Registration:
    contract: ValidityContract
    evaluator: Evaluator


class ClinicalValidityEngine:
    """Registry + dispatcher for derived clinical metrics.

    Generic on purpose: it knows nothing about eGFR, corrected calcium, or
    any other specific metric. `evaluate` only decides whether the inputs
    satisfy the contract's `required_inputs`; the actual computation (and any
    metric-specific precondition/limitation logic) is delegated entirely to
    the registered evaluator.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}

    def register(self, contract: ValidityContract, evaluator: Evaluator) -> None:
        self._registrations[contract.metric_id] = _Registration(
            contract=contract, evaluator=evaluator
        )

    def evaluate(self, metric_id: str, inputs: Mapping[str, Any]) -> ValidityResult:
        registration = self._registrations.get(metric_id)
        if registration is None:
            return ValidityResult(
                metric_id=metric_id,
                version="unknown",
                status=ValidityStatus.NOT_APPLICABLE,
                value=None,
                unit=None,
                failed_preconditions=(),
                limitations=(),
                detail=f"no metric registered for metric_id {metric_id!r}",
            )

        contract = registration.contract
        missing = tuple(
            name for name in contract.required_inputs if name not in inputs or inputs[name] is None
        )
        if missing:
            return ValidityResult(
                metric_id=contract.metric_id,
                version=contract.version,
                status=ValidityStatus.INSUFFICIENT_DATA,
                value=None,
                unit=None,
                failed_preconditions=missing,
                limitations=(),
                detail=f"missing required input(s): {', '.join(missing)}",
            )

        return registration.evaluator(inputs)
