"""The outer self-improving loop (Phase C).

Reads the collected signals (automated gate/Model-B outcomes + clinician
CONFIRM/OVERRIDE/CORRECT labels from Phase B), proposes ONE improvement to
an AUTO-tier component, and promotes it ONLY if it beats a frozen benchmark
and regresses nothing -- while being structurally forbidden from ever
changing clinical rules, the validity math, or the fail-closed gate. See
`ARCHITECTURE.md`'s "self-improving loop" section for the tier boundary
this package enforces and never crosses.

Module map:
  - `models.py`      -- data shapes + the tier boundary (`ImproveTarget`).
  - `errors.py`       -- `ImproveError`, `FrozenTargetError`.
  - `collector.py`     -- join automated signals + clinician labels into a `Dataset`.
  - `proposer.py`     -- the hard guard (`assert_target_allowed`) + `propose_candidate`.
  - `evaluator.py`    -- score a candidate; the hermetic default `ScoreFn`.
  - `promote.py`      -- the append-only `PromotionLedger` + `canary_compare`.
  - `registry.py`     -- `resolve_artifact` (opt-in consumption seam).
  - `cycle.py`         -- `run_improvement_cycle`, the fail-closed orchestrator.
"""

from __future__ import annotations

from app.improve.collector import collect_dataset
from app.improve.cycle import run_improvement_cycle
from app.improve.errors import FrozenTargetError, ImproveError
from app.improve.evaluator import ScoreFn, build_benchmark_score_fn, evaluate_candidate
from app.improve.models import (
    Candidate,
    Dataset,
    EvaluationResult,
    ImprovementReport,
    ImproveTarget,
    Metrics,
    PromotionRecord,
    TrainingCase,
)
from app.improve.promote import PromotionLedger, canary_compare
from app.improve.proposer import Generator, assert_target_allowed, propose_candidate
from app.improve.registry import resolve_artifact

__all__ = [
    "Candidate",
    "Dataset",
    "EvaluationResult",
    "FrozenTargetError",
    "Generator",
    "ImproveError",
    "ImproveTarget",
    "ImprovementReport",
    "Metrics",
    "PromotionLedger",
    "PromotionRecord",
    "ScoreFn",
    "TrainingCase",
    "assert_target_allowed",
    "build_benchmark_score_fn",
    "canary_compare",
    "collect_dataset",
    "evaluate_candidate",
    "propose_candidate",
    "resolve_artifact",
    "run_improvement_cycle",
]
