"""The full pre-Model-B deterministic layer (§22.1 Set D defences).

Combines patient-fact integrity checks (`app.review.integrity`) with
citation checking (`app.citation.verifier`, Gates 1-4). Every Set D
corruption category in `app.review.corruption` must be caught HERE, with
zero calls to Model B -- catching an already-mechanical corruption with a
second, non-deterministic, billable LLM call would be strictly worse
(slower, non-reproducible, costs money) than catching it in this layer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.citation.models import CitationResult, CitationVerdict
from app.citation.verifier import verify_citation
from app.evidence.models import EvidenceSnapshot
from app.review.integrity import check_patient_fact_integrity
from app.review.models import ClaimUnderReview, IntegrityFailure

__all__ = ["DeterministicOutcome", "run_deterministic_layer"]


class DeterministicOutcome(BaseModel):
    """The result of running the full deterministic layer on one claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blocked: bool
    integrity_failures: tuple[IntegrityFailure, ...]
    citation_results: tuple[CitationResult, ...]
    reasons: tuple[str, ...]


def run_deterministic_layer(
    cur: ClaimUnderReview, *, snapshot: EvidenceSnapshot
) -> DeterministicOutcome:
    """Run patient-fact integrity and citation Gates 1-4; block on any hard failure.

    `blocked` is True iff any integrity failure was found OR any citation
    verdict is `REJECT`. A citation `FLAG_FOR_REVIEW` does NOT block here
    (an ambiguous span is routed for review, not treated as a hard failure)
    but is still recorded in `citation_results` and reflected in `reasons`.
    """
    integrity_failures = tuple(check_patient_fact_integrity(cur))

    citation_results = tuple(
        verify_citation(ref, snapshot=snapshot, claim_type=cur.claim.claim_type)
        for ref in cur.claim.external_evidence
    )

    reasons: list[str] = [
        f"integrity failure: {failure.kind.value} on resource_id={failure.resource_id!r} "
        f"({failure.detail})"
        for failure in integrity_failures
    ]
    for result in citation_results:
        if result.verdict == CitationVerdict.REJECT:
            reasons.append(
                f"citation rejected: evidence_id={result.evidence_id!r} snapshot_id="
                f"{result.snapshot_id!r}"
            )
        elif result.verdict == CitationVerdict.FLAG_FOR_REVIEW:
            reasons.append(
                f"citation flagged for review (not blocking): evidence_id={result.evidence_id!r}"
            )

    blocked = bool(integrity_failures) or any(
        result.verdict == CitationVerdict.REJECT for result in citation_results
    )

    return DeterministicOutcome(
        blocked=blocked,
        integrity_failures=integrity_failures,
        citation_results=citation_results,
        reasons=tuple(reasons),
    )
