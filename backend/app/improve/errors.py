"""Errors for the outer self-improving loop (Phase C).

`FrozenTargetError` is the hard stop this whole package exists to make
impossible to bypass: raised by `app.improve.proposer.assert_target_allowed`
(called at BOTH proposal entry and immediately before promotion -- defense
in depth) for any target that is not one of the AUTO-tier
`app.improve.models.ImproveTarget` values.
"""

from __future__ import annotations

__all__ = ["ImproveError", "FrozenTargetError"]


class ImproveError(Exception):
    """Base error for the `app.improve` package."""


class FrozenTargetError(ImproveError):
    """Raised when a proposal or promotion targets a FROZEN-tier component
    (clinical rules, validity math, the final gate, normalization) instead
    of an AUTO-tier `app.improve.models.ImproveTarget`. Always a hard stop,
    never a warning -- catching this anywhere in this package must reject
    the candidate, never proceed."""
