"""§67.7/§67.8/§67.9: a fabrication can never be VERIFIED.

Builds a CLEAN base `ClaimUnderReview` from Patient A's real chart data (the
same 6.2 mmol/L potassium value and active lisinopril order the demo cassette
`tests/fixtures/demo/cassettes/patient_a.json` reasons over) plus the real
demo evidence snapshot's openFDA hyperkalemia citation, matching the shape
`app.review.corruption` documents as required for its corruption functions:
at least one asserted observation and one asserted medication that match the
chart exactly, and one external-evidence ref whose span occurs verbatim,
once, with a valid content hash.

For each Set D corruption category that fabricates a resource id, a value,
or a citation (`nonexistent_resource_id`, `numeric_mismatch`,
`citation_span_absent`, `citation_hash_mismatch`), this module applies the
corruption, runs the real deterministic layer, and then calls
`finalize_claim_verdict` with a Model B verdict that is DELIBERATELY
supportive (`should_reject=False`) -- proving `app.gate.claim_gate`'s §65.4
invariant holds for every one of these categories: a deterministic gate
failure forces REJECTED and cannot be overridden by a probabilistic model
into an accepting verdict, no matter what that model says.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.evidence.models import EvidenceSnapshot
from app.gate.claim_gate import finalize_claim_verdict
from app.gate.models import ClaimVerdict
from app.normalize.medication import normalize_medication_order
from app.normalize.observation import normalize_observation
from app.pipeline.demo_evidence import load_demo_snapshot
from app.review.corruption import (
    citation_hash_mismatch,
    citation_span_absent,
    nonexistent_resource_id,
    numeric_mismatch,
)
from app.review.deterministic import run_deterministic_layer
from app.review.models import (
    AssertedMedication,
    AssertedObservationValue,
    ClaimUnderReview,
    ModelBVerdict,
    PatientFactIndex,
    ReviewFinding,
)
from app.rules.models import Severity

_DEMO_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
_PATIENT_A_PATH = _DEMO_DIR / "patient_a.json"
_EVIDENCE_ID = "openfda:e81a8aca-0e7c-4a02-b596-09e4ac22c70e:adverse_reactions"
_SUPPORTING_SPAN = "Hyperkalemia [see Warnings and Precautions (5.6) ]"

#: A deliberately SUPPORTIVE Model B verdict -- proving the corrupted cases
#: below are rejected regardless of what Model B thinks, never because
#: Model B happened to agree they were bad.
_SUPPORTIVE_MODEL_B_VERDICT = ModelBVerdict(
    finding=ReviewFinding.SUPPORTED,
    should_reject=False,
    rationale=(
        "Deliberately supportive fixture verdict: proves a deterministic REJECTED "
        "can never be overridden by Model B accepting the claim (spec §65.4)."
    ),
    suggested_safer_wording=None,
)


def build_clean_patient_a_base() -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Build the clean base `ClaimUnderReview` + `EvidenceSnapshot` every
    corruption case in this module starts from."""
    bundle = json.loads(_PATIENT_A_PATH.read_text(encoding="utf-8"))
    resources = [entry["resource"] for entry in bundle["entry"]]

    observations = {
        r["id"]: normalize_observation(r) for r in resources if r["resourceType"] == "Observation"
    }
    medications = {
        r["id"]: normalize_medication_order(r)
        for r in resources
        if r["resourceType"] == "MedicationRequest"
    }
    patient_index = PatientFactIndex(
        patient_id="patient-a", observations=observations, medications=medications
    )

    claim = Claim(
        claim_id="claim-a-1",
        claim_type=ClaimType.POSSIBLE_CONCERN,
        statement=(
            "The patient's potassium is critically elevated at 6.2 mmol/L while she is "
            "on an active ACE inhibitor (lisinopril), which may worsen hyperkalemia."
        ),
        patient_evidence=[
            PatientEvidenceRef(resource_type="Observation", resource_id="obs-a-k1"),
            PatientEvidenceRef(resource_type="MedicationRequest", resource_id="med-a-1"),
        ],
        external_evidence=[
            ExternalEvidenceRef(evidence_id=_EVIDENCE_ID, verbatim_supporting_span=_SUPPORTING_SPAN)
        ],
        severity=Severity.CRITICAL,
        confidence=0.85,
        rationale=(
            "Potassium exceeds the critical hyperkalemia threshold while on an active ACE "
            "inhibitor, and the cited label text lists hyperkalemia as a known adverse "
            "reaction for this drug class."
        ),
        recommended_action="Consider an urgent repeat potassium level.",
    )

    cur = ClaimUnderReview(
        claim=claim,
        asserted_observations=(
            AssertedObservationValue(
                resource_id="obs-a-k1", analyte="potassium", value=Decimal("6.2"), unit="mmol/L"
            ),
        ),
        asserted_medications=(AssertedMedication(resource_id="med-a-1", ingredient="lisinopril"),),
        patient_index=patient_index,
        rule_results=(),
    )
    snapshot = load_demo_snapshot()
    return cur, snapshot


def test_base_claim_is_clean_before_any_corruption() -> None:
    """Sanity: the fixture every other test in this module corrupts starts unblocked."""
    cur, snapshot = build_clean_patient_a_base()

    outcome = run_deterministic_layer(cur, snapshot=snapshot)

    assert outcome.blocked is False
    assert outcome.integrity_failures == ()


_SET_D_FABRICATION_CORRUPTIONS = {
    "nonexistent_resource_id": nonexistent_resource_id,
    "numeric_mismatch": numeric_mismatch,
    "citation_span_absent": citation_span_absent,
    "citation_hash_mismatch": citation_hash_mismatch,
}


@pytest.mark.parametrize(
    "corruption_name",
    sorted(_SET_D_FABRICATION_CORRUPTIONS),
    ids=sorted(_SET_D_FABRICATION_CORRUPTIONS),
)
def test_fabrication_is_rejected_even_when_model_b_supports_it(corruption_name: str) -> None:
    """A fabricated resource id, value, or citation is REJECTED by
    `finalize_claim_verdict` even when the Model B verdict passed in is
    `should_reject=False` -- the deterministic gate wins unconditionally."""
    cur, snapshot = build_clean_patient_a_base()
    corrupt = _SET_D_FABRICATION_CORRUPTIONS[corruption_name]
    corrupted_cur, corrupted_snapshot = corrupt(cur, snapshot)

    outcome = run_deterministic_layer(corrupted_cur, snapshot=corrupted_snapshot)
    assert outcome.blocked is True, f"{corruption_name} was not caught by the deterministic layer"

    verdict = finalize_claim_verdict(
        claim_type=corrupted_cur.claim.claim_type,
        external_evidence_required=True,
        has_external_evidence=bool(corrupted_cur.claim.external_evidence),
        integrity_failures=outcome.integrity_failures,
        citation_results=outcome.citation_results,
        model_b_verdict=_SUPPORTIVE_MODEL_B_VERDICT,
        any_cited_evidence_pending_review=False,
    )

    assert verdict == ClaimVerdict.REJECTED, (
        f"{corruption_name} must be REJECTED even though Model B supported it, got {verdict!r}"
    )
