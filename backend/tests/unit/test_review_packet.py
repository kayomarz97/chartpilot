"""Tests for `app.review.packet.build_model_b_packet` (spec §21.1, §21.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.citation.verifier import verify_citation
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier, Jurisdiction
from app.normalize.models import AbnormalityBasis, NormalizedObservation, ObservationStatus
from app.normalize.temporal import parse_fhir_datetime
from app.normalize.units import NormalizedQuantity
from app.review.models import AssertedObservationValue, ClaimUnderReview, PatientFactIndex
from app.review.packet import build_model_b_packet
from app.rules.models import RuleResult, RuleVerdict, Severity

_SUPPORTING_SPAN = "Hyperkalemia has been reported with concomitant use of this medication class."
_RECORD_CONTENT = (
    "WARNINGS AND PRECAUTIONS: Hyperkalemia has been reported with concomitant use of this "
    "medication class. Monitor serum potassium periodically, particularly in patients with "
    "renal impairment or those taking potassium-sparing diuretics."
)


def _build_claim_under_review() -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    record = EvidenceRecord(
        id="evidence-1",
        tier=EvidenceTier.LITERATURE,
        title="Drug Label Excerpt",
        publisher="Test Publisher",
        jurisdiction=Jurisdiction.US_FDA,
        publication_date="2024-01-01",
        version="1",
        content=_RECORD_CONTENT,
        content_hash=content_hash(_RECORD_CONTENT),
        source_url="https://example.invalid/label",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        metadata={},
    )
    snapshot = EvidenceSnapshot(
        snapshot_id="snap-1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        records=(record,),
        manifest_hash="deadbeef",
    )

    claim = Claim(
        claim_id="claim-1",
        claim_type=ClaimType.PATIENT_SPECIFIC_INFERENCE,
        statement="The patient's potassium is elevated, consistent with the cited label warning.",
        patient_evidence=[PatientEvidenceRef(resource_type="Observation", resource_id="obs-1")],
        external_evidence=[
            ExternalEvidenceRef(evidence_id="evidence-1", verbatim_supporting_span=_SUPPORTING_SPAN)
        ],
        severity=Severity.HIGH,
        confidence=0.987654,
        rationale="SECRET_MODEL_A_RATIONALE_TOKEN -- must never reach Model B.",
        recommended_action="SECRET_MODEL_A_RECOMMENDED_ACTION_TOKEN",
    )

    observation = NormalizedObservation(
        id="obs-1",
        code="2823-3",
        code_system="http://loinc.org",
        display="Potassium",
        status=ObservationStatus.FINAL,
        value=NormalizedQuantity(
            value=Decimal("5.6"),
            unit="mmol/L",
            original_value=Decimal("5.6"),
            original_unit="mmol/L",
        ),
        data_absent_reason=None,
        interpretation=["H"],
        reference_ranges=[],
        components=[],
        effective=parse_fhir_datetime("2026-01-01T10:00:00+00:00"),
        issued=None,
        notes=[],
        source_resource_id="obs-1",
        normalization_warnings=[],
    )

    patient_index = PatientFactIndex(
        patient_id="patient-1",
        observations={"obs-1": observation},
        medications={},
    )

    rule_result = RuleResult(
        rule_id="hyperkalemia-check",
        rule_version="1.0",
        verdict=RuleVerdict.FIRED,
        severity=Severity.HIGH,
        matched_observation_ids=("obs-1",),
        matched_medication_ids=(),
        normalized_values={"obs-1": "5.6 mmol/L"},
        abnormality_basis=AbnormalityBasis.REFERENCE_RANGE,
        matched_effective_times=("2026-01-01T10:00:00+00:00",),
        rationale="Potassium exceeds the upper reference bound.",
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    cur = ClaimUnderReview(
        claim=claim,
        asserted_observations=(
            AssertedObservationValue(
                resource_id="obs-1", analyte="potassium", value=Decimal("5.6"), unit="mmol/L"
            ),
        ),
        asserted_medications=(),
        patient_index=patient_index,
        rule_results=(rule_result,),
    )
    return cur, snapshot


def test_packet_excludes_model_a_rationale_confidence_action_severity() -> None:
    """§21.1: the blinded packet must never carry A's reasoning/self-report fields."""
    cur, snapshot = _build_claim_under_review()
    citation_results = tuple(
        verify_citation(ref, snapshot=snapshot, claim_type=cur.claim.claim_type)
        for ref in cur.claim.external_evidence
    )

    packet = build_model_b_packet(cur, snapshot=snapshot, citation_results=citation_results)

    dumped = packet.model_dump_json()
    assert "SECRET_MODEL_A_RATIONALE_TOKEN" not in dumped
    assert "SECRET_MODEL_A_RECOMMENDED_ACTION_TOKEN" not in dumped
    assert "987654" not in dumped
    # No field name that could carry these values exists on ModelBPacket at all.
    schema_field_names = set(packet.model_dump().keys())
    assert schema_field_names.isdisjoint(
        {"rationale", "confidence", "recommended_action", "severity"}
    )


def test_packet_evidence_region_is_the_full_record_not_just_the_span() -> None:
    """§21.2: evidence_regions carries the WHOLE record content, not A's span."""
    cur, snapshot = _build_claim_under_review()
    citation_results = tuple(
        verify_citation(ref, snapshot=snapshot, claim_type=cur.claim.claim_type)
        for ref in cur.claim.external_evidence
    )

    packet = build_model_b_packet(cur, snapshot=snapshot, citation_results=citation_results)

    assert len(packet.evidence_regions) == 1
    region = packet.evidence_regions[0]
    assert region.evidence_id == "evidence-1"
    assert region.full_region_text == _RECORD_CONTENT
    assert region.full_region_text != _SUPPORTING_SPAN
    assert len(region.full_region_text) > len(_SUPPORTING_SPAN)
    assert _SUPPORTING_SPAN in region.full_region_text


def test_packet_carries_claim_statement_and_type_but_nothing_else_of_claim() -> None:
    """The packet is blinded, not empty: it still needs the bare statement/type."""
    cur, snapshot = _build_claim_under_review()
    citation_results = tuple(
        verify_citation(ref, snapshot=snapshot, claim_type=cur.claim.claim_type)
        for ref in cur.claim.external_evidence
    )

    packet = build_model_b_packet(cur, snapshot=snapshot, citation_results=citation_results)

    assert packet.claim_statement == cur.claim.statement
    assert packet.claim_type == cur.claim.claim_type
    assert len(packet.rule_outputs) == 1
    assert "hyperkalemia-check" in packet.rule_outputs[0]
    assert len(packet.citation_gate_results) == 1
    assert "evidence-1" in packet.citation_gate_results[0]
