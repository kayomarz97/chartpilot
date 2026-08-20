"""Tests for `app.review.corruption`: Set D / Set M / measure_suite / release gate."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier, Jurisdiction
from app.normalize.medication import MedicationOrderStatus, NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation, ObservationStatus
from app.normalize.temporal import parse_fhir_datetime
from app.normalize.units import NormalizedQuantity
from app.review.corruption import (
    SET_D_CORRUPTIONS,
    SET_M_CORRUPTIONS,
    CorruptionCase,
    CorruptionSet,
    build_set_d_cases,
    build_set_m_cases,
    measure_suite,
    release_threshold_met,
)
from app.review.deterministic import DeterministicOutcome, run_deterministic_layer
from app.review.models import (
    AssertedMedication,
    AssertedObservationValue,
    ClaimUnderReview,
    ModelBPacket,
    ModelBVerdict,
    PatientFactIndex,
    ReviewFinding,
    SuiteReport,
)

_SUPPORTING_SPAN = "Hyperkalemia has been reported with concomitant use of this medication class."
_RECORD_CONTENT = (
    "WARNINGS AND PRECAUTIONS: Hyperkalemia has been reported with concomitant use of this "
    "medication class. Monitor serum potassium periodically in at-risk patients."
)


def _build_clean_base() -> tuple[ClaimUnderReview, EvidenceSnapshot]:
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
        statement="The patient's potassium is elevated while on lisinopril.",
        patient_evidence=[
            PatientEvidenceRef(resource_type="Observation", resource_id="obs-1"),
            PatientEvidenceRef(resource_type="MedicationRequest", resource_id="med-1"),
        ],
        external_evidence=[
            ExternalEvidenceRef(evidence_id="evidence-1", verbatim_supporting_span=_SUPPORTING_SPAN)
        ],
        severity=None,
        confidence=0.6,
        rationale="rationale text",
        recommended_action=None,
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
    medication = NormalizedMedicationOrder(
        id="med-1",
        medication_code="29046",
        medication_display="Lisinopril 10 MG Oral Tablet",
        code_system="http://www.nlm.nih.gov/research/umls/rxnorm",
        status=MedicationOrderStatus.ACTIVE,
        authored_on=parse_fhir_datetime("2025-06-01T00:00:00+00:00"),
        intent="order",
    )

    patient_index = PatientFactIndex(
        patient_id="patient-1",
        observations={"obs-1": observation},
        medications={"med-1": medication},
    )

    cur = ClaimUnderReview(
        claim=claim,
        asserted_observations=(
            AssertedObservationValue(
                resource_id="obs-1", analyte="potassium", value=Decimal("5.6"), unit="mmol/L"
            ),
        ),
        asserted_medications=(AssertedMedication(resource_id="med-1", ingredient="lisinopril"),),
        patient_index=patient_index,
        rule_results=(),
    )
    return cur, snapshot


def _deterministic_runner(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> DeterministicOutcome:
    return run_deterministic_layer(cur, snapshot=snapshot)


def test_base_claim_is_clean_before_any_corruption() -> None:
    """Sanity: the fixture used by every other test in this module is unblocked."""
    cur, snapshot = _build_clean_base()

    outcome = run_deterministic_layer(cur, snapshot=snapshot)

    assert outcome.blocked is False
    assert outcome.integrity_failures == ()


def test_every_set_d_corruption_is_blocked_deterministically() -> None:
    cur, snapshot = _build_clean_base()
    cases = build_set_d_cases(cur, snapshot)

    assert len(cases) == 7 == len(SET_D_CORRUPTIONS)
    for case in cases:
        outcome = run_deterministic_layer(case.claim_under_review, snapshot=case.snapshot)
        assert outcome.blocked is True, (
            f"Set D case {case.name!r} was not blocked deterministically"
        )


def test_every_set_m_corruption_passes_deterministic_layer_unblocked() -> None:
    cur, snapshot = _build_clean_base()
    cases = build_set_m_cases(cur, snapshot)

    assert len(cases) == 8 == len(SET_M_CORRUPTIONS)
    for case in cases:
        outcome = run_deterministic_layer(case.claim_under_review, snapshot=case.snapshot)
        assert outcome.blocked is False, f"Set M case {case.name!r} was unexpectedly blocked"


def test_measure_suite_never_calls_model_b_on_set_d() -> None:
    cur, snapshot = _build_clean_base()
    set_d_cases = build_set_d_cases(cur, snapshot)
    set_m_cases = build_set_m_cases(cur, snapshot)
    control_cases = [
        CorruptionCase(
            name="control",
            corruption_set=CorruptionSet.MODEL_ONLY,
            claim_under_review=cur,
            snapshot=snapshot,
        )
    ]

    called_names: list[str] = []

    def fake_run_model_b(name: str, packet: ModelBPacket) -> ModelBVerdict:
        called_names.append(name)
        if name in SET_M_CORRUPTIONS:
            return ModelBVerdict(
                finding=ReviewFinding.CONTRADICTED,
                should_reject=True,
                rationale="caught by Model B",
            )
        return ModelBVerdict(finding=ReviewFinding.SUPPORTED, should_reject=False, rationale="fine")

    report = measure_suite(
        set_d=set_d_cases,
        set_m=set_m_cases,
        control=control_cases,
        run_deterministic=_deterministic_runner,
        run_model_b=fake_run_model_b,
    )

    assert isinstance(report, SuiteReport)
    assert report.set_d_total == 7
    assert report.set_d_blocked_pre_b == 7
    assert set(SET_D_CORRUPTIONS).isdisjoint(called_names)
    assert "control" in called_names

    assert report.set_m_total == 8
    assert report.set_m_caught == 8
    assert report.set_m_missed == 0
    assert report.set_m_catch_rate == 1.0
    assert report.false_accept == 0
    assert report.false_reject == 0
    assert report.control_total == 1


def test_release_threshold_met_when_everything_catches() -> None:
    cur, snapshot = _build_clean_base()
    set_d_cases = build_set_d_cases(cur, snapshot)
    set_m_cases = build_set_m_cases(cur, snapshot)
    control_cases = [
        CorruptionCase(
            name="control",
            corruption_set=CorruptionSet.MODEL_ONLY,
            claim_under_review=cur,
            snapshot=snapshot,
        )
    ]

    def fake_run_model_b(name: str, packet: ModelBPacket) -> ModelBVerdict:
        should_reject = name in SET_M_CORRUPTIONS
        finding = ReviewFinding.CONTRADICTED if should_reject else ReviewFinding.SUPPORTED
        return ModelBVerdict(finding=finding, should_reject=should_reject, rationale="fake verdict")

    report = measure_suite(
        set_d=set_d_cases,
        set_m=set_m_cases,
        control=control_cases,
        run_deterministic=_deterministic_runner,
        run_model_b=fake_run_model_b,
    )

    assert release_threshold_met(report) is True


def test_release_threshold_met_false_when_a_set_d_case_is_not_blocked() -> None:
    cur, snapshot = _build_clean_base()
    set_d_cases = build_set_d_cases(cur, snapshot)
    set_m_cases = build_set_m_cases(cur, snapshot)

    def fake_run_model_b(name: str, packet: ModelBPacket) -> ModelBVerdict:
        should_reject = name in SET_M_CORRUPTIONS
        finding = ReviewFinding.CONTRADICTED if should_reject else ReviewFinding.SUPPORTED
        return ModelBVerdict(finding=finding, should_reject=should_reject, rationale="fake verdict")

    good_report = measure_suite(
        set_d=set_d_cases,
        set_m=set_m_cases,
        control=[],
        run_deterministic=_deterministic_runner,
        run_model_b=fake_run_model_b,
    )
    # Simulate one Set D corruption "reaching Model B" (i.e. not blocked
    # deterministically) by reducing set_d_blocked_pre_b below set_d_total.
    degraded_report = good_report.model_copy(
        update={"set_d_blocked_pre_b": good_report.set_d_total - 1}
    )

    assert release_threshold_met(degraded_report) is False


def test_release_threshold_met_false_when_set_m_catch_rate_below_threshold() -> None:
    cur, snapshot = _build_clean_base()
    set_d_cases = build_set_d_cases(cur, snapshot)
    set_m_cases = build_set_m_cases(cur, snapshot)

    def fake_run_model_b_never_catches(name: str, packet: ModelBPacket) -> ModelBVerdict:
        return ModelBVerdict(
            finding=ReviewFinding.SUPPORTED, should_reject=False, rationale="missed"
        )

    report = measure_suite(
        set_d=set_d_cases,
        set_m=set_m_cases,
        control=[],
        run_deterministic=_deterministic_runner,
        run_model_b=fake_run_model_b_never_catches,
    )

    assert report.set_m_catch_rate == 0.0
    assert release_threshold_met(report) is False
