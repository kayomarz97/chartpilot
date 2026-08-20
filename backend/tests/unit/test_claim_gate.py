"""Tests for `app.gate.claim_gate.finalize_claim_verdict` (spec §42, §65.4).

The core invariant under test throughout: once ANY deterministic gate has
failed (patient-fact integrity, citation REJECT), the verdict can NEVER be
VERIFIED -- not even when Model B would have accepted the claim.
"""

from __future__ import annotations

from app.agent.models import ClaimType
from app.citation.models import CitationResult, CitationVerdict
from app.gate.claim_gate import finalize_claim_verdict
from app.gate.models import ClaimVerdict
from app.review.models import IntegrityFailure, IntegrityFailureKind, ModelBVerdict, ReviewFinding


def _citation_result(verdict: CitationVerdict, evidence_id: str = "ev-1") -> CitationResult:
    return CitationResult(
        evidence_id=evidence_id,
        snapshot_id="snap-1",
        verdict=verdict,
        gates=(),
        raw_span="some text",
        normalized_span="some text",
        computed_start_offset=0,
        computed_end_offset=9,
        artifact_content_hash="deadbeef",
    )


def _integrity_failure() -> IntegrityFailure:
    return IntegrityFailure(
        kind=IntegrityFailureKind.NUMERIC_MISMATCH,
        resource_id="obs-1",
        detail="claimed 5.0, chart has 7.0",
    )


def _model_b_verdict(*, should_reject: bool) -> ModelBVerdict:
    return ModelBVerdict(
        finding=ReviewFinding.CONTRADICTED if should_reject else ReviewFinding.SUPPORTED,
        should_reject=should_reject,
        rationale="because",
    )


def test_integrity_failure_forces_rejected_even_if_model_b_accepts() -> None:
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.PATIENT_FACT,
        external_evidence_required=False,
        has_external_evidence=False,
        integrity_failures=[_integrity_failure()],
        citation_results=[],
        model_b_verdict=_model_b_verdict(should_reject=False),
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.REJECTED


def test_citation_reject_forces_rejected_even_if_model_b_accepts() -> None:
    """The core Phase 10 invariant (spec §65.4): a deterministic gate
    failure can never be overridden into VERIFIED by Model B."""
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.GUIDELINE_RECOMMENDATION,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=[],
        citation_results=[_citation_result(CitationVerdict.REJECT)],
        model_b_verdict=_model_b_verdict(should_reject=False),
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.REJECTED


def test_citation_flag_for_review_routes_to_requires_review() -> None:
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.GUIDELINE_RECOMMENDATION,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=[],
        citation_results=[_citation_result(CitationVerdict.FLAG_FOR_REVIEW)],
        model_b_verdict=None,
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.REQUIRES_REVIEW


def test_model_b_disagreement_routes_to_requires_review_not_verified() -> None:
    """Model A asserts, Model B falsifies -- a disagreement, routed to a
    human. Never averaged, never resolved by confidence, never dropped."""
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.PATIENT_SPECIFIC_INFERENCE,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=[],
        citation_results=[_citation_result(CitationVerdict.VERIFIED_SPAN)],
        model_b_verdict=_model_b_verdict(should_reject=True),
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.REQUIRES_REVIEW


def test_pending_review_evidence_caps_at_partially_verified() -> None:
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.GUIDELINE_RECOMMENDATION,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=[],
        citation_results=[_citation_result(CitationVerdict.VERIFIED_SPAN)],
        model_b_verdict=_model_b_verdict(should_reject=False),
        any_cited_evidence_pending_review=True,
    )
    assert verdict == ClaimVerdict.PARTIALLY_VERIFIED


def test_all_gates_pass_and_model_b_accepts_yields_verified() -> None:
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.GUIDELINE_RECOMMENDATION,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=[],
        citation_results=[_citation_result(CitationVerdict.VERIFIED_SPAN)],
        model_b_verdict=_model_b_verdict(should_reject=False),
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.VERIFIED


def test_missing_required_external_evidence_yields_unverifiable() -> None:
    verdict = finalize_claim_verdict(
        claim_type=ClaimType.REGULATORY_FACT,
        external_evidence_required=True,
        has_external_evidence=False,
        integrity_failures=[],
        citation_results=[],
        model_b_verdict=None,
        any_cited_evidence_pending_review=False,
    )
    assert verdict == ClaimVerdict.UNVERIFIABLE
