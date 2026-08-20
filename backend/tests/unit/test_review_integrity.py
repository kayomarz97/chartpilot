"""Tests for `app.review.integrity.check_patient_fact_integrity`."""

from __future__ import annotations

from decimal import Decimal

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.normalize.medication import MedicationOrderStatus, NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation, ObservationStatus
from app.normalize.temporal import parse_fhir_datetime
from app.normalize.units import NormalizedQuantity
from app.review.integrity import check_patient_fact_integrity
from app.review.models import (
    AssertedMedication,
    AssertedObservationValue,
    ClaimUnderReview,
    IntegrityFailureKind,
    PatientFactIndex,
)


def _observation() -> NormalizedObservation:
    return NormalizedObservation(
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


def _medication() -> NormalizedMedicationOrder:
    return NormalizedMedicationOrder(
        id="med-1",
        medication_code="29046",
        medication_display="Lisinopril 10 MG Oral Tablet",
        code_system="http://www.nlm.nih.gov/research/umls/rxnorm",
        status=MedicationOrderStatus.ACTIVE,
        authored_on=parse_fhir_datetime("2025-06-01T00:00:00+00:00"),
        intent="order",
    )


def _claim() -> Claim:
    return Claim(
        claim_id="claim-1",
        claim_type=ClaimType.PATIENT_SPECIFIC_INFERENCE,
        statement="The patient's potassium is elevated on lisinopril.",
        patient_evidence=[
            PatientEvidenceRef(resource_type="Observation", resource_id="obs-1"),
            PatientEvidenceRef(resource_type="MedicationRequest", resource_id="med-1"),
        ],
        external_evidence=[
            ExternalEvidenceRef(evidence_id="evidence-1", verbatim_supporting_span="some span")
        ],
        severity=None,
        confidence=0.5,
        rationale="rationale text",
        recommended_action=None,
    )


def _clean_claim_under_review() -> ClaimUnderReview:
    patient_index = PatientFactIndex(
        patient_id="patient-1",
        observations={"obs-1": _observation()},
        medications={"med-1": _medication()},
    )
    return ClaimUnderReview(
        claim=_claim(),
        asserted_observations=(
            AssertedObservationValue(
                resource_id="obs-1", analyte="potassium", value=Decimal("5.6"), unit="mmol/L"
            ),
        ),
        asserted_medications=(AssertedMedication(resource_id="med-1", ingredient="lisinopril"),),
        patient_index=patient_index,
        rule_results=(),
    )


def test_clean_claim_has_no_integrity_failures() -> None:
    cur = _clean_claim_under_review()

    failures = check_patient_fact_integrity(cur)

    assert failures == []


def test_numeric_mismatch_detected() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_observations": (
                AssertedObservationValue(
                    resource_id="obs-1", analyte="potassium", value=Decimal("9.9"), unit="mmol/L"
                ),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert len(failures) == 1
    assert failures[0].kind == IntegrityFailureKind.NUMERIC_MISMATCH
    assert failures[0].resource_id == "obs-1"


def test_wrong_drug_detected() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_medications": (
                AssertedMedication(resource_id="med-1", ingredient="metformin"),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert len(failures) == 1
    assert failures[0].kind == IntegrityFailureKind.WRONG_DRUG
    assert failures[0].resource_id == "med-1"


def test_nonexistent_observation_resource_id_detected() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_observations": (
                AssertedObservationValue(
                    resource_id="obs-does-not-exist",
                    analyte="potassium",
                    value=Decimal("5.6"),
                    unit="mmol/L",
                ),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert len(failures) == 1
    assert failures[0].kind == IntegrityFailureKind.RESOURCE_NOT_FOUND
    assert failures[0].resource_id == "obs-does-not-exist"


def test_nonexistent_medication_resource_id_detected() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_medications": (
                AssertedMedication(resource_id="med-does-not-exist", ingredient="lisinopril"),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert len(failures) == 1
    assert failures[0].kind == IntegrityFailureKind.RESOURCE_NOT_FOUND
    assert failures[0].resource_id == "med-does-not-exist"


def test_date_mismatch_detected() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_observations": (
                AssertedObservationValue(
                    resource_id="obs-1",
                    analyte="potassium",
                    value=Decimal("5.6"),
                    unit="mmol/L",
                    effective_source="1900-01-01T00:00:00+00:00",
                ),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert len(failures) == 1
    assert failures[0].kind == IntegrityFailureKind.DATE_MISMATCH
    assert failures[0].resource_id == "obs-1"


def test_effective_source_matching_chart_is_clean() -> None:
    cur = _clean_claim_under_review()
    corrupted = cur.model_copy(
        update={
            "asserted_observations": (
                AssertedObservationValue(
                    resource_id="obs-1",
                    analyte="potassium",
                    value=Decimal("5.6"),
                    unit="mmol/L",
                    effective_source="2026-01-01T10:00:00+00:00",
                ),
            )
        }
    )

    failures = check_patient_fact_integrity(corrupted)

    assert failures == []
