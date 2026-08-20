"""§13: a stale or contradicted source is surfaced to a human, never silently
resolved.

Reuses the CLEAN Patient A base (`tests/adversarial/test_fabrication_rejected.
build_clean_patient_a_base`): a claim that passes every deterministic gate
(patient facts match the chart, the citation span verifies). Model B is run
through the hermetic `FakeGeminiClient` -- exactly as `app.pipeline.runner`
wires it in production -- with a cassette verdict of `finding=STALE_SOURCE,
should_reject=True` in one case and `finding=CONTRADICTED, should_reject=True`
in the other.

`app.gate.claim_gate.finalize_claim_verdict` routes ANY `should_reject=True`
Model B verdict to REQUIRES_REVIEW once the deterministic gates have passed
(gate 5) -- it never averages, never silently accepts the majority model, and
never resolves the conflict on its own. That routing IS the §13 mechanism:
same-claim-type conflict (a claim Model A supports, that a real citation
verifies, but whose SOURCE Model B independently flags as stale or
contradicted elsewhere in its own text) is surfaced via Model B + the human
review verdict, not resolved by the pipeline itself.
"""

from __future__ import annotations

import json

import pytest

from app.gate.claim_gate import finalize_claim_verdict
from app.gate.models import ClaimVerdict
from app.review.deterministic import run_deterministic_layer
from app.review.models import ReviewFinding
from app.review.packet import build_model_b_packet
from app.review.reviewer import run_model_b
from tests.adversarial.test_fabrication_rejected import build_clean_patient_a_base
from tests.support.fake_gemini import FakeGeminiClient


@pytest.mark.parametrize("finding", [ReviewFinding.STALE_SOURCE, ReviewFinding.CONTRADICTED])
def test_stale_or_contradicted_source_routes_to_requires_review(finding: ReviewFinding) -> None:
    cur, snapshot = build_clean_patient_a_base()

    outcome = run_deterministic_layer(cur, snapshot=snapshot)
    assert outcome.blocked is False, "base claim must pass every deterministic gate"

    packet = build_model_b_packet(cur, snapshot=snapshot, citation_results=outcome.citation_results)
    verdict_json = json.dumps(
        {
            "finding": finding.value,
            "should_reject": True,
            "rationale": (
                f"Model B independently flags this claim's source as {finding.value}, "
                "conflicting with Model A's and the citation gate's acceptance of it."
            ),
            "suggested_safer_wording": None,
        }
    )
    model_b_client = FakeGeminiClient([(cur.claim.statement, verdict_json)])
    model_b_verdict = run_model_b(model_b_client, packet)

    assert model_b_verdict.finding == finding
    assert model_b_verdict.should_reject is True

    final_verdict = finalize_claim_verdict(
        claim_type=cur.claim.claim_type,
        external_evidence_required=True,
        has_external_evidence=True,
        integrity_failures=outcome.integrity_failures,
        citation_results=outcome.citation_results,
        model_b_verdict=model_b_verdict,
        any_cited_evidence_pending_review=False,
    )

    assert final_verdict == ClaimVerdict.REQUIRES_REVIEW


def test_conflict_is_never_silently_resolved_to_verified() -> None:
    """The negative half of the same invariant: a should_reject=True verdict
    of either flavor must NEVER reach VERIFIED, no matter how "confident"
    Model A/the citation gate were upstream."""
    cur, snapshot = build_clean_patient_a_base()
    outcome = run_deterministic_layer(cur, snapshot=snapshot)

    for finding in (ReviewFinding.STALE_SOURCE, ReviewFinding.CONTRADICTED):
        packet = build_model_b_packet(
            cur, snapshot=snapshot, citation_results=outcome.citation_results
        )
        verdict_json = json.dumps(
            {
                "finding": finding.value,
                "should_reject": True,
                "rationale": "conflicting source",
                "suggested_safer_wording": None,
            }
        )
        model_b_verdict = run_model_b(
            FakeGeminiClient([(cur.claim.statement, verdict_json)]), packet
        )

        final_verdict = finalize_claim_verdict(
            claim_type=cur.claim.claim_type,
            external_evidence_required=True,
            has_external_evidence=True,
            integrity_failures=outcome.integrity_failures,
            citation_results=outcome.citation_results,
            model_b_verdict=model_b_verdict,
            any_cited_evidence_pending_review=False,
        )
        assert final_verdict != ClaimVerdict.VERIFIED
