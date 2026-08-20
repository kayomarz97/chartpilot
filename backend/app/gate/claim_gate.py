"""Final per-claim verdict gate (spec §42, §65.4).

Folds every upstream deterministic and semi-deterministic signal -- patient-
fact integrity (`app.review.integrity`), citation gates 1-4
(`app.citation.verifier`), and Model B's independent review
(`app.review.reviewer`) -- into a single `ClaimVerdict`. Pure function, no
I/O, no LLM calls: everything it needs has already been computed upstream.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.models import ClaimType
from app.citation.models import CitationResult, CitationVerdict
from app.gate.models import ClaimVerdict
from app.review.models import IntegrityFailure, ModelBVerdict

__all__ = ["finalize_claim_verdict"]


def finalize_claim_verdict(
    *,
    claim_type: ClaimType,
    external_evidence_required: bool,
    has_external_evidence: bool,
    integrity_failures: Sequence[IntegrityFailure],
    citation_results: Sequence[CitationResult],
    model_b_verdict: ModelBVerdict | None,
    any_cited_evidence_pending_review: bool,
) -> ClaimVerdict:
    """Compute the final verdict for one claim (spec §42).

    Fail-closed, deterministic, and evaluated in a fixed order with short-
    circuit: gates are checked from hardest failure to softest, and Model B
    is only ever consulted once every deterministic gate has already
    passed.

    INVARIANT (spec §65.4, the load-bearing Phase 10 rule): no path through
    this function returns VERIFIED once a deterministic gate has failed. A
    patient-fact integrity failure or a citation REJECT verdict forces
    REJECTED regardless of what Model B (or anything else) would have said
    -- a deterministic gate failing can never be overridden by a
    probabilistic model into an accepting verdict. `claim_type` is accepted
    for future extension/observability but does not currently change the
    ordering below; every claim type is subject to the same gate order.
    """
    # `claim_type` is not currently used to branch verdict logic -- every
    # claim type is subject to the same gate order (spec §42) -- but is
    # accepted as an explicit part of the call signature for future
    # extension/observability.
    _ = claim_type

    # 1. Patient-fact integrity failed -> REJECTED (spec §22.1).
    if integrity_failures:
        return ClaimVerdict.REJECTED

    # 2. A citation gate hard-rejected the evidence -> REJECTED. This can
    #    NEVER be overridden by Model B accepting the claim (spec §65.4).
    if any(result.verdict == CitationVerdict.REJECT for result in citation_results):
        return ClaimVerdict.REJECTED

    # 3. A citation was ambiguous enough to need a human -> REQUIRES_REVIEW.
    if any(result.verdict == CitationVerdict.FLAG_FOR_REVIEW for result in citation_results):
        return ClaimVerdict.REQUIRES_REVIEW

    # 4. External evidence was required but never supplied -> UNVERIFIABLE.
    if external_evidence_required and not has_external_evidence:
        return ClaimVerdict.UNVERIFIABLE

    # 5. All deterministic gates have passed. Consult Model B.
    if model_b_verdict is not None and model_b_verdict.should_reject:
        # Model A asserted the claim; Model B independently falsifies it.
        # A DISAGREEMENT between the two models is routed to a human --
        # never averaged, never resolved by confidence, never silently
        # dropped (spec §9, §65.4).
        return ClaimVerdict.REQUIRES_REVIEW

    # Model B is absent (not run) or agrees with the claim.
    if any_cited_evidence_pending_review:
        # A `reviewed_by: PENDING` guideline record caps the claim at
        # PARTIALLY_VERIFIED -- it cannot be a full VERIFIED until that
        # underlying evidence record itself clears human review (spec §12).
        return ClaimVerdict.PARTIALLY_VERIFIED

    return ClaimVerdict.VERIFIED
