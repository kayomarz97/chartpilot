"""Resolve which artifact VALUE a consumer (e.g. Model A's prompt builder)
should use at the start of a run: the ledger's active promoted version if
one exists, else the pinned default constant.

This is the seam that keeps the loop's learned artifacts from ever
hot-mutating a running pinned constant (spec: determinism preserved). An
EMPTY ledger (no promotions ever made -- true of every deployment today)
makes `resolve_artifact` return exactly `default`, so wiring a call site to
this function with `ledger=None` (or a fresh, empty `PromotionLedger`) is
byte-identical to not calling it at all.

Deliberately NOT wired into `app.pipeline.runner.run_patient` by this
phase: doing so is a live-consumption decision with its own blast radius
(a promoted prompt actually driving Model A calls in production) that
belongs to a later, explicitly-reviewed change -- see `ARCHITECTURE.md`'s
"self-improving loop" section. This function exists so that future change
has a resolver to call; it is not called from anywhere in the live pipeline
today.
"""

from __future__ import annotations

from app.improve.models import ImproveTarget
from app.improve.promote import PromotionLedger

__all__ = ["resolve_artifact"]


def resolve_artifact(
    target: ImproveTarget, default: str, *, ledger: PromotionLedger | None = None
) -> str:
    """Return the active promoted value for `target` from `ledger`, or
    `default` if `ledger` is `None` or has no active version yet.

    Resolution happens ONCE per call by design -- a caller must call this
    once at the top of a run (never mid-run) and hold the result for that
    run's duration, to preserve the determinism guarantee: which artifact
    version drove a given run must never change while that run is in
    flight.
    """
    if ledger is None:
        return default
    value = ledger.active_value(target)
    return default if value is None else value
