"""Orchestrate ONE Phase C improvement cycle: collect -> split -> propose
(train) -> evaluate (holdout) -> canary -> promote, or reject.

Fail-closed by construction: `propose`/`evaluate`/`canary`/`promote` are
each wrapped so that ANY exception -- a bug in a generator, a `score_fn`
that raises, a filesystem error while writing the ledger -- yields a
REJECTED `ImprovementReport` (`accepted=False`) with the error captured in
`detail`. This function never raises and never promotes on uncertainty.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.improve.collector import collect_dataset
from app.improve.evaluator import ScoreFn, evaluate_candidate
from app.improve.models import ImprovementReport, ImproveTarget
from app.improve.promote import PromotionLedger, canary_compare
from app.improve.proposer import Generator, assert_target_allowed, propose_candidate

__all__ = ["run_improvement_cycle"]


def run_improvement_cycle(
    *,
    presentations: list[dict[str, Any]],
    clinician_actions: list[dict[str, Any]],
    target: ImproveTarget,
    generate: Generator,
    score_fn: ScoreFn,
    ledger: PromotionLedger,
    now: datetime,
    version: str,
) -> ImprovementReport:
    """Run one full Phase C cycle for `target` and return its
    `ImprovementReport` -- always, never an exception."""
    active_value = ledger.active_value(target) or ""

    try:
        dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)
        candidate = propose_candidate(dataset, target=target, generate=generate)
        evaluation = evaluate_candidate(candidate, active_value=active_value, score_fn=score_fn)
    except Exception as exc:  # noqa: BLE001 -- fail-closed by design, see module docstring
        return ImprovementReport(
            target=target,
            accepted=False,
            evaluation=None,
            promotion=None,
            detail=f"rejected (fail-closed): error during propose/evaluate: {exc!r}",
        )

    if not evaluation.accept:
        return ImprovementReport(
            target=target,
            accepted=False,
            evaluation=evaluation,
            promotion=None,
            detail="rejected: evaluation did not accept the candidate",
        )

    try:
        # Defense in depth: re-guard immediately before promotion, even
        # though propose_candidate already guarded `target` and the
        # returned candidate's target.
        assert_target_allowed(target)
        if not canary_compare(candidate.new_value, active_value, score_fn=score_fn):
            return ImprovementReport(
                target=target,
                accepted=False,
                evaluation=evaluation,
                promotion=None,
                detail="rejected: canary comparison regressed against the active value",
            )
        promotion = ledger.promote(
            target, candidate.new_value, version=version, rationale=candidate.rationale, now=now
        )
    except Exception as exc:  # noqa: BLE001 -- fail-closed by design, see module docstring
        return ImprovementReport(
            target=target,
            accepted=False,
            evaluation=evaluation,
            promotion=None,
            detail=f"rejected (fail-closed): error during canary/promotion: {exc!r}",
        )

    return ImprovementReport(
        target=target,
        accepted=True,
        evaluation=evaluation,
        promotion=promotion,
        detail="accepted and promoted",
    )
