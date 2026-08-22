"""The hard tier guard, plus the entry point that proposes ONE candidate
change for exactly one AUTO-tier target.

`assert_target_allowed` is the single choke point every proposal AND every
promotion must pass through (spec: "defense in depth" -- called again,
independently, in every concrete `app.improve.ledger.PromotionLedger`
implementation's `.promote()` (`FilePromotionLedger`, `InMemoryPromotionLedger`,
`FirestorePromotionLedger`) and `app.improve.cycle.run_improvement_cycle`, not
trusted to have already run).
It is default-deny: anything that is not a value of `app.improve.models.
ImproveTarget` is refused, whether or not it happens to be a KNOWN frozen
name (`app.improve.models.FROZEN_TARGET_NAMES`) -- a brand-new FROZEN
component this guard has never heard of is refused exactly the same way.
"""

from __future__ import annotations

from collections.abc import Callable

from app.improve.errors import FrozenTargetError
from app.improve.models import FROZEN_TARGET_NAMES, Candidate, Dataset, ImproveTarget

__all__ = ["AUTO_TIER_TARGETS", "Generator", "assert_target_allowed", "propose_candidate"]

#: Every string value an AUTO-tier `ImproveTarget` may take -- the allowlist
#: `assert_target_allowed` checks membership against.
AUTO_TIER_TARGETS: frozenset[str] = frozenset(target.value for target in ImproveTarget)

#: A candidate-proposing function: given the TRAIN split of the dataset and
#: the target to propose a change for, return one `Candidate`. Implementations
#: range from a hermetic test fake to a future live-model-backed proposer
#: (see `app.api.composition.get_improve_generator`) -- this package makes no
#: assumption about which.
Generator = Callable[[Dataset, ImproveTarget], Candidate]


def assert_target_allowed(target: str) -> None:
    """Raise `FrozenTargetError` unless `target` is a value of an AUTO-tier
    `ImproveTarget`. Default-deny: an unrecognized target is refused exactly
    like a known FROZEN one -- this function never has to be told about a
    new FROZEN component to keep refusing it.
    """
    if target in AUTO_TIER_TARGETS:
        return
    if target in FROZEN_TARGET_NAMES:
        raise FrozenTargetError(
            f"target {target!r} is a FROZEN-tier identifier and can never be a "
            "self-improvement candidate target"
        )
    raise FrozenTargetError(
        f"target {target!r} is not an AUTO-tier improvement target "
        f"(allowed: {sorted(AUTO_TIER_TARGETS)}); refusing by default"
    )


def propose_candidate(dataset: Dataset, *, target: ImproveTarget, generate: Generator) -> Candidate:
    """Propose ONE `Candidate` for `target`, generated from ONLY the TRAIN
    split of `dataset` (never the holdout -- see `Dataset.split`'s docstring
    for why: the holdout must never influence what gets proposed, only
    whether it gets accepted).

    Guards `target` before calling `generate`, then re-validates the
    returned `Candidate.target` through the SAME guard before returning it
    -- a generator that (buggily, or adversarially) returns a candidate
    aimed at a FROZEN target is refused here, never silently passed on to
    `evaluate_candidate`/`promote`.
    """
    assert_target_allowed(target)
    train, _holdout = dataset.split()
    candidate = generate(train, target)
    assert_target_allowed(candidate.target)
    return candidate
