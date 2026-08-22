"""Errors for the outer self-improving loop (Phase C).

`FrozenTargetError` is the hard stop this whole package exists to make
impossible to bypass: raised by `app.improve.proposer.assert_target_allowed`
(called at BOTH proposal entry and immediately before promotion -- defense
in depth) for any target that is not one of the AUTO-tier
`app.improve.models.ImproveTarget` values.
"""

from __future__ import annotations

__all__ = ["ImproveError", "FrozenTargetError", "ProposerOutputError"]


class ImproveError(Exception):
    """Base error for the `app.improve` package."""


class FrozenTargetError(ImproveError):
    """Raised when a proposal or promotion targets a FROZEN-tier component
    (clinical rules, validity math, the final gate, normalization) instead
    of an AUTO-tier `app.improve.models.ImproveTarget`. Always a hard stop,
    never a warning -- catching this anywhere in this package must reject
    the candidate, never proceed."""


class ProposerOutputError(ImproveError):
    """A live LLM-backed proposer's (`app.improve.proposer_llm.LlmProposer`)
    structured output failed to validate. Mirrors `app.agent.errors.
    StructuredOutputError`'s fail-closed contract (raised on ANY
    `pydantic.ValidationError`, original exception chained as `__cause__`)
    without making `app.improve` depend on the agent layer's own error
    hierarchy."""
