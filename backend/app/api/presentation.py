"""Build the UI-shaped "presentation" payload from a `PatientRunResult`
(TD-011).

Pure, side-effect-free mapping from the pipeline's internal result shapes
(`app.pipeline.models.PatientRunResult`) to the exact camelCase JSON shape
the frontend expects (`frontend/lib/types.ts`: `PatientRun`, `Finding`,
`TimelineEvent`, `LabTrend`). Computed once per patient at the end of
`app.api.composition.run_demo_patient` and persisted via
`RunRepository.upsert_presentation` -- never recomputed on the public read
path (`GET /runs/{run_id}`), so that endpoint stays a cheap read.

Only fields this module can actually derive from `PatientRunResult` are
populated; anything that would require data not carried on that result
(e.g. a cited `EvidenceRecord`'s `tier`/`publisher`/`sourceUrl` -- the full
`EvidenceSnapshot` is not part of `PatientRunResult`) is simply omitted from
the JSON dict rather than invented or defaulted to a fabricated value.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.agent.models import ExternalEvidenceRef, PatientEvidenceRef
from app.citation.models import CitationResult
from app.normalize.medication import NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation
from app.normalize.observation import latest_valid_observation
from app.normalize.units import NormalizedQuantity
from app.pipeline.models import FindingResult, PatientRunResult
from app.pipeline.runner import _ANALYTE_BY_CODE
from app.review.models import ModelBVerdict
from app.validation.metrics import EGFR_METRIC_ID
from app.validation.models import ValidityResult, ValidityStatus

__all__ = ["build_presentation"]

#: The FHIR code creatinine is normalized under (mirrors
#: `app.pipeline.runner._evaluate_validity_metrics`), used here to pair a
#: computed eGFR result back with the creatinine reading it was derived
#: from -- `ValidityResult` itself carries no source-observation date.
_CREATININE_CODE = "2160-0"

# ---------------------------------------------------------------------------
# Lab reference thresholds -- CONSERVATIVE, adult/non-pregnant, standard
# reference intervals as commonly cited in US lab reporting. This is
# synthetic demo data support, NOT clinical decision support; do not treat
# these as a source of truth for real patient care.
#
#   - potassium (mmol/L): normal ~3.5-5.0; CRITICAL <2.5 or >6.5 (values
#     associated with life-threatening arrhythmia risk).
#   - sodium (mmol/L): normal ~135-145; CRITICAL <120 or >160 (severe
#     hypo-/hypernatremia).
#   - creatinine (mg/dL): normal ~0.6-1.3; CRITICAL >4.0 (severe renal
#     impairment range). No LOW side flagged (a low creatinine is not a
#     standard renal-danger signal).
#   - eGFR (mL/min/1.73m2): INVERTED -- a LOW value is the dangerous
#     direction. LOW <60 (CKD stage 3+), CRITICAL <15 (kidney failure,
#     CKD stage 5). No HIGH side flagged.
# ---------------------------------------------------------------------------


class _Threshold:
    """One analyte's flagging thresholds. `inverted=True` means LOW is the
    dangerous direction (e.g. eGFR), not HIGH."""

    __slots__ = ("low", "high", "critical_low", "critical_high", "inverted")

    def __init__(
        self,
        *,
        low: Decimal | None = None,
        high: Decimal | None = None,
        critical_low: Decimal | None = None,
        critical_high: Decimal | None = None,
        inverted: bool = False,
    ) -> None:
        self.low = low
        self.high = high
        self.critical_low = critical_low
        self.critical_high = critical_high
        self.inverted = inverted


_LAB_THRESHOLDS: dict[str, _Threshold] = {
    "potassium": _Threshold(
        low=Decimal("3.5"),
        high=Decimal("5.0"),
        critical_low=Decimal("2.5"),
        critical_high=Decimal("6.5"),
    ),
    "sodium": _Threshold(
        low=Decimal("135"),
        high=Decimal("145"),
        critical_low=Decimal("120"),
        critical_high=Decimal("160"),
    ),
    "creatinine": _Threshold(high=Decimal("1.3"), critical_high=Decimal("4.0")),
    "egfr": _Threshold(low=Decimal("60"), critical_low=Decimal("15"), inverted=True),
}


def _flag_for(analyte: str, value: Decimal) -> str | None:
    """Return `"HIGH"`/`"LOW"`/`"CRITICAL"`, or `None` if within range or
    the analyte has no registered threshold."""
    threshold = _LAB_THRESHOLDS.get(analyte)
    if threshold is None:
        return None
    if threshold.inverted:
        if threshold.critical_low is not None and value < threshold.critical_low:
            return "CRITICAL"
        if threshold.low is not None and value < threshold.low:
            return "LOW"
        return None
    if threshold.critical_high is not None and value > threshold.critical_high:
        return "CRITICAL"
    if threshold.critical_low is not None and value < threshold.critical_low:
        return "CRITICAL"
    if threshold.high is not None and value > threshold.high:
        return "HIGH"
    if threshold.low is not None and value < threshold.low:
        return "LOW"
    return None


def _observation_value_str(obs: NormalizedObservation) -> str:
    if obs.value is None:
        return "(no value)"
    if isinstance(obs.value, NormalizedQuantity):
        return f"{obs.value.value} {obs.value.unit}"
    return obs.value


def _label_for_resource_type(resource_type: str) -> str:
    if resource_type == "Observation":
        return "Lab Result"
    if resource_type == "MedicationRequest":
        return "Medication"
    return resource_type


def _patient_evidence_detail(
    ref: PatientEvidenceRef,
    observations_by_id: dict[str, NormalizedObservation],
    medications_by_id: dict[str, NormalizedMedicationOrder],
) -> str:
    if ref.resource_type == "Observation":
        obs = observations_by_id.get(ref.resource_id)
        if obs is None:
            return f"resource_id={ref.resource_id} (not found in chart)"
        analyte = _ANALYTE_BY_CODE.get(obs.code, obs.display or obs.code)
        return f"{analyte}: {_observation_value_str(obs)}"
    if ref.resource_type == "MedicationRequest":
        med = medications_by_id.get(ref.resource_id)
        if med is None:
            return f"resource_id={ref.resource_id} (not found in chart)"
        display = med.medication_display or med.medication_code or med.id
        return f"{display}: {med.status.value}"
    return f"resource_id={ref.resource_id}"


def _build_external_evidence(
    ref: ExternalEvidenceRef,
    citation_results_by_id: dict[str, CitationResult],
    model_b_verdict: ModelBVerdict | None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "evidenceId": ref.evidence_id,
        "verbatimSpan": ref.verbatim_supporting_span,
    }
    citation = citation_results_by_id.get(ref.evidence_id)
    if citation is not None:
        item["citationVerdict"] = citation.verdict.value.upper()
        item["gatesPassed"] = [{"gate": g.gate.value, "passed": g.passed} for g in citation.gates]
        if citation.computed_start_offset is not None:
            item["computedStartOffset"] = citation.computed_start_offset
        if citation.computed_end_offset is not None:
            item["computedEndOffset"] = citation.computed_end_offset
        if citation.snapshot_id is not None:
            item["snapshotId"] = citation.snapshot_id
    if model_b_verdict is not None:
        # Model B reviews the whole claim, not individual citations -- its
        # verdict is attached to every external-evidence item of that claim.
        item["modelBFinding"] = model_b_verdict.finding.value.upper()
        item["modelBShouldReject"] = model_b_verdict.should_reject
    return item


def _build_finding(
    finding: FindingResult,
    observations_by_id: dict[str, NormalizedObservation],
    medications_by_id: dict[str, NormalizedMedicationOrder],
) -> dict[str, Any]:
    claim = finding.claim
    citation_results_by_id = {c.evidence_id: c for c in finding.citation_results}
    return {
        "claimId": claim.claim_id,
        "claimType": claim.claim_type.value.upper(),
        "statement": claim.statement,
        "severity": claim.severity.value.upper() if claim.severity is not None else None,
        "verdict": finding.verdict.value.upper(),
        "rationale": claim.rationale,
        "recommendedAction": claim.recommended_action or "",
        "patientEvidence": [
            {
                "label": _label_for_resource_type(ref.resource_type),
                "detail": _patient_evidence_detail(ref, observations_by_id, medications_by_id),
            }
            for ref in claim.patient_evidence
        ],
        "externalEvidence": [
            _build_external_evidence(ref, citation_results_by_id, finding.model_b_verdict)
            for ref in claim.external_evidence
        ],
    }


def _build_timeline(result: PatientRunResult) -> list[dict[str, Any]]:
    """Build structured timeline events from normalized observations,
    medications, and adverse reactions, sorted by date descending.

    An event whose source timestamp has no determinable position on the
    timeline (`ClinicalInstant.value_utc is None`, i.e. `Precision.ABSENT`)
    is dropped rather than guessed -- it cannot be placed or sorted.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    for obs in result.normalized_observations:
        if obs.effective.value_utc is None:
            continue
        date_str = obs.effective.value_utc.isoformat()
        analyte = _ANALYTE_BY_CODE.get(obs.code, obs.display or obs.code)
        event: dict[str, Any] = {
            "date": date_str,
            "kind": "LAB",
            "label": f"{analyte}: {_observation_value_str(obs)}",
            "detail": f"status={obs.status.value}",
        }
        if isinstance(obs.value, NormalizedQuantity):
            flag = _flag_for(analyte, obs.value.value)
            if flag is not None:
                event["severity"] = flag
        events.append((date_str, event))

    for med in result.normalized_medications:
        if med.authored_on.value_utc is None:
            continue
        date_str = med.authored_on.value_utc.isoformat()
        label = med.medication_display or med.medication_code or "medication"
        events.append(
            (
                date_str,
                {
                    "date": date_str,
                    "kind": "MEDICATION",
                    "label": label,
                    "detail": f"status={med.status.value}",
                },
            )
        )

    for adr in result.normalized_adverse_reactions:
        if adr.recorded.value_utc is None:
            continue
        date_str = adr.recorded.value_utc.isoformat()
        label = adr.causative_agent or adr.manifestation or "adverse reaction"
        detail = f"kind={adr.kind.value}"
        if adr.manifestation:
            detail += f"; manifestation={adr.manifestation}"
        events.append(
            (
                date_str,
                {
                    "date": date_str,
                    "kind": "ADVERSE_EVENT",
                    "label": label,
                    "detail": detail,
                },
            )
        )

    events.sort(key=lambda pair: pair[0], reverse=True)
    return [event for _, event in events]


def _build_labs(result: PatientRunResult) -> list[dict[str, Any]]:
    """Group normalized numeric observations by analyte into time-ordered
    lab trends, plus a best-effort `eGFR` pseudo-analyte from the run's
    validity results. Only analytes with at least one dated numeric point
    are included."""
    points_by_analyte: dict[str, list[tuple[str, Decimal]]] = {}
    unit_by_analyte: dict[str, str] = {}

    for obs in result.normalized_observations:
        if not isinstance(obs.value, NormalizedQuantity):
            continue
        if obs.effective.value_utc is None:
            continue
        analyte = _ANALYTE_BY_CODE.get(obs.code)
        if analyte is None:
            continue
        date_str = obs.effective.value_utc.date().isoformat()
        points_by_analyte.setdefault(analyte, []).append((date_str, obs.value.value))
        unit_by_analyte[analyte] = obs.value.unit

    egfr_result: ValidityResult | None = next(
        (
            r
            for r in result.validity_results
            if r.metric_id == EGFR_METRIC_ID
            and r.value is not None
            and r.status in (ValidityStatus.VALID, ValidityStatus.VALID_WITH_LIMITATIONS)
        ),
        None,
    )
    if egfr_result is not None:
        creatinine_obs = latest_valid_observation(
            list(result.normalized_observations), code=_CREATININE_CODE
        )
        if creatinine_obs is not None and creatinine_obs.effective.value_utc is not None:
            date_str = creatinine_obs.effective.value_utc.date().isoformat()
            assert egfr_result.value is not None  # narrowed by the filter above
            points_by_analyte.setdefault("egfr", []).append((date_str, egfr_result.value))
            unit_by_analyte["egfr"] = egfr_result.unit or "mL/min/1.73m2"

    labs: list[dict[str, Any]] = []
    for analyte in sorted(points_by_analyte):
        points = sorted(points_by_analyte[analyte], key=lambda p: p[0])
        labs.append(
            {
                "analyte": analyte,
                "unit": unit_by_analyte[analyte],
                "points": [
                    {
                        "date": date_str,
                        "value": float(value),
                        **({"flag": flag} if (flag := _flag_for(analyte, value)) else {}),
                    }
                    for date_str, value in points
                ],
            }
        )
    return labs


def build_presentation(result: PatientRunResult, *, patient_name: str) -> dict[str, Any]:
    """Build the UI-shaped presentation payload for one patient run.

    Pure function of `result` (plus the caller-supplied `patient_name`,
    kept as an explicit parameter rather than always reading
    `result.patient_name` so this function stays independently testable
    with a hand-built `PatientRunResult`).
    """
    observations_by_id = {obs.id: obs for obs in result.normalized_observations}
    medications_by_id = {med.id: med for med in result.normalized_medications}

    return {
        "patientId": result.patient_id,
        "patientName": patient_name,
        "status": result.summary.status.value.upper(),
        "stage": result.summary.stage.value,
        "findings": [
            _build_finding(finding, observations_by_id, medications_by_id)
            for finding in result.findings
        ],
        "timeline": _build_timeline(result),
        "labs": _build_labs(result),
    }
