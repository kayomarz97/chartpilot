"""Hermetic tests for `app.api.presentation.build_presentation` (TD-011):
the pure mapping from `PatientRunResult` to the UI-shaped JSON payload
`frontend/lib/types.ts` (`PatientRun`) expects.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.api.presentation import build_presentation
from app.citation.models import CitationResult, CitationVerdict, GateName, GateResult
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.normalize.medication import MedicationOrderStatus, NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation, ObservationStatus
from app.normalize.temporal import ClinicalInstant, Precision
from app.normalize.units import NormalizedQuantity
from app.pipeline.models import FindingResult, PatientRunResult, PatientRunSummary
from app.review.models import ModelBVerdict, ReviewFinding
from app.rules.models import Severity
from app.validation.metrics import EGFR_METRIC_ID
from app.validation.models import ValidityResult, ValidityStatus


def _instant(day: str) -> ClinicalInstant:
    return ClinicalInstant(
        value_utc=datetime.fromisoformat(f"{day}T00:00:00+00:00"),
        precision=Precision.DAY,
        source_string=day,
        source_offset_present=False,
    )


def _quantity(value: str, unit: str) -> NormalizedQuantity:
    return NormalizedQuantity(
        value=Decimal(value), unit=unit, original_value=Decimal(value), original_unit=unit
    )


def _potassium_obs(day: str, value: str) -> NormalizedObservation:
    return NormalizedObservation(
        id="obs-k",
        code="2823-3",
        code_system="http://loinc.org",
        display="Potassium",
        status=ObservationStatus.FINAL,
        value=_quantity(value, "mmol/L"),
        data_absent_reason=None,
        interpretation=[],
        reference_ranges=[],
        components=[],
        effective=_instant(day),
        issued=None,
        notes=[],
        source_resource_id="obs-k",
        normalization_warnings=[],
    )


def _creatinine_obs(day: str, value: str) -> NormalizedObservation:
    return NormalizedObservation(
        id="obs-cr",
        code="2160-0",
        code_system="http://loinc.org",
        display="Creatinine",
        status=ObservationStatus.FINAL,
        value=_quantity(value, "mg/dL"),
        data_absent_reason=None,
        interpretation=[],
        reference_ranges=[],
        components=[],
        effective=_instant(day),
        issued=None,
        notes=[],
        source_resource_id="obs-cr",
        normalization_warnings=[],
    )


def _medication(day: str) -> NormalizedMedicationOrder:
    return NormalizedMedicationOrder(
        id="med-1",
        medication_code="29046",
        medication_display="Lisinopril 10mg",
        code_system="http://www.nlm.nih.gov/research/umls/rxnorm",
        status=MedicationOrderStatus.ACTIVE,
        authored_on=_instant(day),
        intent="order",
    )


def _claim() -> Claim:
    return Claim(
        claim_id="claim-1",
        claim_type=ClaimType.POSSIBLE_CONCERN,
        statement="Potassium is critically elevated on ACE inhibitor therapy.",
        patient_evidence=[
            PatientEvidenceRef(resource_type="Observation", resource_id="obs-k"),
            PatientEvidenceRef(resource_type="MedicationRequest", resource_id="med-1"),
            PatientEvidenceRef(resource_type="Observation", resource_id="obs-missing"),
        ],
        external_evidence=[
            ExternalEvidenceRef(evidence_id="ev-1", verbatim_supporting_span="hyperkalemia risk")
        ],
        severity=Severity.HIGH,
        confidence=0.9,
        rationale="K+ 6.8 mmol/L exceeds critical threshold while on lisinopril.",
        recommended_action="Recheck potassium urgently and consider holding ACEi.",
    )


def _finding(*, revision_attempts: int = 0) -> FindingResult:
    citation = CitationResult(
        evidence_id="ev-1",
        snapshot_id="snap-1",
        verdict=CitationVerdict.VERIFIED_SPAN,
        gates=(GateResult(gate=GateName.SOURCE_RETRIEVAL, passed=True, detail="ok"),),
        raw_span="hyperkalemia risk",
        normalized_span="hyperkalemia risk",
        computed_start_offset=10,
        computed_end_offset=28,
        artifact_content_hash="deadbeef",
    )
    model_b = ModelBVerdict(
        finding=ReviewFinding.SUPPORTED, should_reject=False, rationale="Consistent with chart."
    )
    return FindingResult(
        claim=_claim(),
        verdict=ClaimVerdict.VERIFIED,
        citation_results=(citation,),
        model_b_verdict=model_b,
        revision_attempts=revision_attempts,
    )


def _result(
    *,
    findings: tuple[FindingResult, ...] = (),
    observations: tuple[NormalizedObservation, ...] = (),
    medications: tuple[NormalizedMedicationOrder, ...] = (),
    validity_results: tuple[ValidityResult, ...] = (),
) -> PatientRunResult:
    return PatientRunResult(
        patient_id="patient-x",
        summary=PatientRunSummary(
            status=PatientStatus.COMPLETED,
            stage=PatientStage.PERSISTED,
            commit_status=CommitStatus.COMMITTED,
        ),
        findings=findings,
        rule_results=(),
        validity_results=validity_results,
        timeline_events=(),
        error=None,
        patient_name="Rosa Alvarez",
        normalized_observations=observations,
        normalized_medications=medications,
        normalized_adverse_reactions=(),
    )


# --------------------------------------------------------------------------
# Top-level shape
# --------------------------------------------------------------------------


def test_build_presentation_top_level_shape() -> None:
    result = _result(observations=(_potassium_obs("2026-01-05", "6.8"),))

    payload = build_presentation(result, patient_name="Rosa Alvarez")

    assert payload["patientId"] == "patient-x"
    assert payload["patientName"] == "Rosa Alvarez"
    assert payload["status"] == "COMPLETED"
    assert payload["stage"] == "persisted"
    assert set(payload.keys()) == {
        "patientId",
        "patientName",
        "status",
        "stage",
        "findings",
        "timeline",
        "labs",
    }


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


def test_build_presentation_finding_shape_and_enum_uppercasing() -> None:
    result = _result(
        findings=(_finding(),),
        observations=(_potassium_obs("2026-01-05", "6.8"),),
        medications=(_medication("2026-01-01"),),
    )

    payload = build_presentation(result, patient_name="Rosa Alvarez")

    assert len(payload["findings"]) == 1
    finding = payload["findings"][0]
    assert finding["claimId"] == "claim-1"
    assert finding["claimType"] == "POSSIBLE_CONCERN"
    assert finding["severity"] == "HIGH"
    assert finding["verdict"] == "VERIFIED"
    assert finding["revisionAttempts"] == 0
    assert finding["recommendedAction"] == "Recheck potassium urgently and consider holding ACEi."

    patient_evidence = finding["patientEvidence"]
    assert len(patient_evidence) == 3
    assert patient_evidence[0] == {"label": "Lab Result", "detail": "potassium: 6.8 mmol/L"}
    assert patient_evidence[1] == {
        "label": "Medication",
        "detail": "Lisinopril 10mg: active",
    }
    # A claim citing a resource id absent from the chart is not silently
    # dropped -- it is reported, not fabricated.
    assert "not found in chart" in patient_evidence[2]["detail"]

    external_evidence = finding["externalEvidence"]
    assert len(external_evidence) == 1
    ev = external_evidence[0]
    assert ev["evidenceId"] == "ev-1"
    assert ev["verbatimSpan"] == "hyperkalemia risk"
    assert ev["citationVerdict"] == "VERIFIED_SPAN"
    assert ev["gatesPassed"] == [{"gate": "source_retrieval", "passed": True}]
    assert ev["computedStartOffset"] == 10
    assert ev["computedEndOffset"] == 28
    assert ev["snapshotId"] == "snap-1"
    assert ev["modelBFinding"] == "SUPPORTED"
    assert ev["modelBShouldReject"] is False
    # Fields we genuinely don't have (no EvidenceSnapshot in scope) must be
    # omitted, never fabricated.
    assert "tier" not in ev
    assert "publisher" not in ev
    assert "sourceUrl" not in ev
    assert "reviewedBy" not in ev


def test_build_presentation_carries_nonzero_revision_attempts() -> None:
    """`FindingResult.revision_attempts` (Phase A's gate-failure -> revise ->
    retry trace field) must survive into the presentation payload so Phase C
    can read it as one of the automated per-finding signals."""
    result = _result(findings=(_finding(revision_attempts=2),))

    payload = build_presentation(result, patient_name="Rosa Alvarez")

    assert payload["findings"][0]["revisionAttempts"] == 2


def test_build_presentation_no_findings_is_empty_list() -> None:
    result = _result()
    payload = build_presentation(result, patient_name="Rosa Alvarez")
    assert payload["findings"] == []


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------


def test_build_presentation_timeline_sorted_desc_with_flags() -> None:
    result = _result(
        observations=(_potassium_obs("2026-01-05", "6.8"),),
        medications=(_medication("2026-01-10"),),
    )

    payload = build_presentation(result, patient_name="Rosa Alvarez")
    timeline = payload["timeline"]

    assert len(timeline) == 2
    # Descending by date: the later medication event comes first.
    assert timeline[0]["kind"] == "MEDICATION"
    assert timeline[0]["date"].startswith("2026-01-10")
    assert timeline[1]["kind"] == "LAB"
    assert timeline[1]["date"].startswith("2026-01-05")
    # Critical potassium (>6.5 mmol/L) is flagged on the LAB event.
    assert timeline[1]["severity"] == "CRITICAL"
    assert "severity" not in timeline[0]


# --------------------------------------------------------------------------
# labs
# --------------------------------------------------------------------------


def test_build_presentation_labs_grouped_by_analyte_with_flags() -> None:
    result = _result(
        observations=(
            _potassium_obs("2026-01-01", "4.0"),
            _potassium_obs("2026-01-05", "6.8"),
            _creatinine_obs("2026-01-05", "1.5"),
        )
    )

    payload = build_presentation(result, patient_name="Rosa Alvarez")
    labs = {lab["analyte"]: lab for lab in payload["labs"]}

    assert set(labs) == {"potassium", "creatinine"}
    k_points = labs["potassium"]["points"]
    assert labs["potassium"]["unit"] == "mmol/L"
    assert [p["date"] for p in k_points] == ["2026-01-01", "2026-01-05"]
    assert "flag" not in k_points[0]
    assert k_points[1]["flag"] == "CRITICAL"

    cr_points = labs["creatinine"]["points"]
    assert cr_points[0]["flag"] == "HIGH"


def test_build_presentation_egfr_pseudo_analyte_paired_with_creatinine_date() -> None:
    egfr = ValidityResult(
        metric_id=EGFR_METRIC_ID,
        version="2021",
        status=ValidityStatus.VALID,
        value=Decimal("55"),
        unit="mL/min/1.73m2",
        failed_preconditions=(),
        limitations=(),
        detail=None,
    )
    result = _result(observations=(_creatinine_obs("2026-01-05", "1.5"),), validity_results=(egfr,))

    payload = build_presentation(result, patient_name="Rosa Alvarez")
    labs = {lab["analyte"]: lab for lab in payload["labs"]}

    assert "egfr" in labs
    assert labs["egfr"]["unit"] == "mL/min/1.73m2"
    assert labs["egfr"]["points"] == [{"date": "2026-01-05", "value": 55.0, "flag": "LOW"}]


def test_build_presentation_omits_analyte_with_no_numeric_points() -> None:
    """A non-numeric or unmapped-code observation never produces a
    zero-point lab trend."""
    text_obs = NormalizedObservation(
        id="obs-note",
        code="99999-9",
        code_system="http://loinc.org",
        display="Narrative note",
        status=ObservationStatus.FINAL,
        value="free text, not a quantity",
        data_absent_reason=None,
        interpretation=[],
        reference_ranges=[],
        components=[],
        effective=_instant("2026-01-01"),
        issued=None,
        notes=[],
        source_resource_id="obs-note",
        normalization_warnings=[],
    )
    result = _result(observations=(text_obs,))

    payload = build_presentation(result, patient_name="Rosa Alvarez")

    assert payload["labs"] == []
