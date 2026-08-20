"""Tests for `app.citation.verifier` (spec Gates 1-4)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.agent.models import ClaimType, ExternalEvidenceRef
from app.citation.models import CitationVerdict, GateName
from app.citation.normalization import normalize_text
from app.citation.verifier import offsets_still_valid, verify_citation
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.snapshot import build_snapshot

RETRIEVED_AT = datetime(2026, 8, 20, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 20, 1, 0, 0, tzinfo=UTC)


def _record(
    record_id: str,
    text: str,
    *,
    tier: EvidenceTier = EvidenceTier.LITERATURE,
    publisher: str = "Example Publisher",
    jurisdiction: Jurisdiction = Jurisdiction.NOT_APPLICABLE,
    stored_hash: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        tier=tier,
        title=f"title-{record_id}",
        publisher=publisher,
        jurisdiction=jurisdiction,
        publication_date="2024",
        version=None,
        content=text,
        content_hash=stored_hash if stored_hash is not None else content_hash(text),
        source_url=f"https://example.invalid/{record_id}",
        retrieved_at=RETRIEVED_AT,
        metadata={},
    )


def _ref(evidence_id: str, span: str) -> ExternalEvidenceRef:
    return ExternalEvidenceRef(evidence_id=evidence_id, verbatim_supporting_span=span)


def test_valid_single_occurrence_span_verifies() -> None:
    record = _record("lit-1", "The patient should avoid grapefruit juice while on this drug.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "avoid grapefruit juice")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.VERIFIED_SPAN
    assert all(g.passed for g in result.gates)
    norm_source = normalize_text(record.content)
    assert result.computed_start_offset is not None
    assert result.computed_end_offset is not None
    assert (
        norm_source[result.computed_start_offset : result.computed_end_offset]
        == result.normalized_span
    )


def test_span_absent_from_source_rejects() -> None:
    record = _record("lit-1", "Some unrelated content about dosing.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "this text is nowhere in the source")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.REJECT
    span_gate = next(g for g in result.gates if g.gate == GateName.SPAN_VERIFICATION)
    assert span_gate.passed is False


def test_span_occurring_twice_flags_for_review() -> None:
    record = _record("lit-1", "Take with food. Take with food, not on an empty stomach.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "Take with food")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.FLAG_FOR_REVIEW
    span_gate = next(g for g in result.gates if g.gate == GateName.SPAN_VERIFICATION)
    assert span_gate.passed is False


def test_unknown_evidence_id_rejects_at_source_retrieval() -> None:
    record = _record("lit-1", "Some content.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("does-not-exist", "Some content.")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.REJECT
    assert len(result.gates) == 1
    assert result.gates[0].gate == GateName.SOURCE_RETRIEVAL
    assert result.gates[0].passed is False


def test_content_hash_mismatch_rejects() -> None:
    record = _record("lit-1", "Some content.", stored_hash="deliberately-wrong-hash")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "Some content.")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.REJECT
    hash_gate = next(g for g in result.gates if g.gate == GateName.CONTENT_HASH)
    assert hash_gate.passed is False


def test_guideline_claim_citing_literature_record_rejects_tier_violation() -> None:
    record = _record(
        "lit-1",
        "Consider ACE inhibitors as first-line therapy.",
        tier=EvidenceTier.LITERATURE,
    )
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "Consider ACE inhibitors as first-line therapy")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.GUIDELINE_RECOMMENDATION)

    assert result.verdict == CitationVerdict.REJECT
    metadata_gate = next(g for g in result.gates if g.gate == GateName.METADATA)
    assert metadata_gate.passed is False


def test_regulatory_fact_citing_regulatory_label_verifies() -> None:
    record = _record(
        "label-1",
        "Contraindicated in patients with severe hepatic impairment.",
        tier=EvidenceTier.REGULATORY_LABEL,
        jurisdiction=Jurisdiction.US_FDA,
    )
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("label-1", "Contraindicated in patients with severe hepatic impairment")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.REGULATORY_FACT)

    assert result.verdict == CitationVerdict.VERIFIED_SPAN


def test_normalization_only_match_verifies_end_to_end() -> None:
    """The §17 key case, exercised through the full verifier: a source with
    an en-dash + NBSP and a model span with an ascii hyphen + normal space
    only match after normalization, but still verify."""
    record = _record("lab-1", "potassium 5–6 mmol/L is within tolerance.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lab-1", "potassium 5-6 mmol/L")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert result.verdict == CitationVerdict.VERIFIED_SPAN


def test_offsets_still_valid_true_for_same_hash() -> None:
    record = _record("lit-1", "Some content that stays the same.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "Some content that stays the same")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    assert offsets_still_valid(result, record) is True


def test_offsets_still_valid_false_for_changed_content() -> None:
    record = _record("lit-1", "Some content that stays the same.")
    snapshot = build_snapshot([record], created_at=CREATED_AT)
    ref = _ref("lit-1", "Some content that stays the same")

    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)

    changed_record = _record("lit-1", "Completely different content now.")
    assert offsets_still_valid(result, changed_record) is False
