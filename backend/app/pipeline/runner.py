"""`run_patient`: chain every prior phase into one end-to-end pipeline run.

FETCHING -> NORMALIZING -> RULES_EVALUATED -> EVIDENCE_RETRIEVAL ->
AI_REASONING -> CITATION_CHECK -> INDEPENDENT_REVIEW -> FINAL_VALIDATION ->
PERSISTED, per `app.gate.models.STAGE_ORDER`. Every stage boundary is
fail-closed: an error at FETCHING/NORMALIZING/AI_REASONING/
INDEPENDENT_REVIEW/FINAL_VALIDATION ends the run FAILED (never a silent
"no findings" result) -- see `_failed_result`.

Asserted-fact note (read before touching `_build_claim_under_review`):
`app.agent.models.Claim.patient_evidence` (the Phase 8 schema) cites WHICH
chart resource a claim's reasoning depends on, but carries no separate
"what value did the model think this resource held" field -- unlike the
hand-built fixtures in `tests/unit/test_review_integrity.py` and
`tests/unit/test_corruption_suite.py`, there is no channel in this schema
version for Model A to assert a value that could disagree with the chart.
Given that, this pipeline treats each cited resource's OWN current
normalized value as its assertion, so `check_patient_fact_integrity` can
still catch the one corruption category reachable through this extraction
path -- a claim citing a resource_id absent from the patient's own chart
(RESOURCE_NOT_FOUND). The full Set D/M corruption suite exercises the other
categories (NUMERIC_MISMATCH, WRONG_DRUG, ...) directly against hand-built
`ClaimUnderReview`s in `app.review.corruption`, not through this path.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from app.agent.claims import generate_claims
from app.agent.models import Claim, ClaimType
from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
from app.agent.protocol import GeminiClient
from app.evidence.guideline_pack import is_clinician_reviewed
from app.evidence.models import EvidenceSnapshot, EvidenceTier
from app.fhir.client import FhirClient
from app.fhir.errors import FhirError
from app.fhir.transport import FhirTransport
from app.gate.claim_gate import finalize_claim_verdict
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage
from app.gate.patient_state import derive_patient_status
from app.normalize.adr import NormalizedAdverseReaction, normalize_adverse_reactions
from app.normalize.medication import NormalizedMedicationOrder, normalize_medication_order
from app.normalize.models import NormalizedObservation
from app.normalize.observation import latest_valid_observation, normalize_observation
from app.normalize.units import NormalizedQuantity
from app.pipeline.models import FindingResult, PatientRunResult, PatientRunSummary
from app.review.deterministic import run_deterministic_layer
from app.review.models import (
    AssertedMedication,
    AssertedObservationValue,
    ClaimUnderReview,
    ModelBVerdict,
    PatientFactIndex,
)
from app.review.packet import build_model_b_packet
from app.review.reviewer import run_model_b
from app.rules.medication_classes import MedicationClasses
from app.rules.models import RuleResult
from app.rules.potassium import KHighRiskConfig, evaluate_k_high_risk
from app.storage.errors import StorageError
from app.storage.inmemory import InMemoryRunRepository
from app.storage.repository import RunRepository
from app.storage.two_phase import finalize_patient_result
from app.validation.metrics import EGFR_METRIC_ID, build_default_engine
from app.validation.models import ValidityResult

__all__ = ["run_patient"]

#: Claim types whose assertion is only meaningfully grounded by external
#: evidence -- a claim of one of these types with NO cited evidence is
#: UNVERIFIABLE rather than VERIFIED (spec §42 step 4). `patient_fact`,
#: `clinician_review_suggestion`, and `uncertainty` are self-contained (a
#: restatement of the chart, a procedural suggestion, or an explicit
#: admission of uncertainty) and never require one.
_EXTERNAL_EVIDENCE_REQUIRED_TYPES = frozenset(
    {
        ClaimType.REGULATORY_FACT,
        ClaimType.GUIDELINE_RECOMMENDATION,
        ClaimType.POSSIBLE_CONCERN,
        ClaimType.PATIENT_SPECIFIC_INFERENCE,
    }
)

_ANALYTE_BY_CODE: dict[str, str] = {
    "2823-3": "potassium",
    "6298-4": "potassium",
    "2951-2": "sodium",
    "2947-0": "sodium",
    "2160-0": "creatinine",
    "38483-4": "creatinine",
}


def run_patient(
    *,
    patient_bundle_ref: str,
    fhir_transport: FhirTransport,
    snapshot: EvidenceSnapshot,
    model_a: GeminiClient,
    model_b: GeminiClient,
    k_config: KHighRiskConfig | None = None,
    med_classes: MedicationClasses | None = None,
    clock: Callable[[], datetime],
    repo: RunRepository | None = None,
    run_id: str = "demo-run",
    stage_timings: dict[str, float] | None = None,
) -> PatientRunResult:
    """Run one patient through the full chained pipeline.

    `repo`/`run_id` are not part of the spec'd call shape but are accepted
    as optional extensions for testability: `repo` defaults to a fresh
    `InMemoryRunRepository` (hermetic, no external state) and `run_id`
    defaults to a stable constant, so a bare `run_patient(...)` call with
    only the documented keyword arguments still works end to end.

    `stage_timings` (spec §50, Phase 17): when given a dict, this call
    records the elapsed WALL-CLOCK seconds (measured with
    `time.perf_counter` -- a monotonic clock for measurement, never a naive
    `datetime`, and never used for any clinical timestamp) each
    `app.gate.models.PatientStage` took, keyed by the stage's `.value`.
    Defaults to `None`, in which case nothing is recorded and this call is
    byte-for-byte the same as before this parameter existed -- zero
    behavior change for every existing caller.
    """
    repository = repo if repo is not None else InMemoryRunRepository()
    now = clock()

    _stage_start = time.perf_counter()

    # --- FETCHING ---
    try:
        resources = FhirClient(fhir_transport).fetch_all(patient_bundle_ref)
    except FhirError as exc:
        _mark_stage(stage_timings, PatientStage.FETCHING, _stage_start)
        return _failed_result(
            patient_id=patient_bundle_ref, stage=PatientStage.FETCHING, error=str(exc)
        )

    patient_resource = next((r for r in resources if r.get("resourceType") == "Patient"), None)
    if patient_resource is None or not patient_resource.get("id"):
        _mark_stage(stage_timings, PatientStage.FETCHING, _stage_start)
        return _failed_result(
            patient_id=patient_bundle_ref,
            stage=PatientStage.FETCHING,
            error="no Patient resource with an id found in the fetched bundle",
        )
    patient_id = str(patient_resource["id"])
    patient_name = _patient_display_name(patient_resource)
    _stage_start = _mark_stage(stage_timings, PatientStage.FETCHING, _stage_start)

    # --- NORMALIZING ---
    try:
        observations = [
            normalize_observation(r) for r in resources if r.get("resourceType") == "Observation"
        ]
        medications = [
            normalize_medication_order(r)
            for r in resources
            if r.get("resourceType") == "MedicationRequest"
        ]
        adverse_reactions = normalize_adverse_reactions(resources)
    except Exception as exc:  # noqa: BLE001 -- fail closed, never silent "no findings"
        _mark_stage(stage_timings, PatientStage.NORMALIZING, _stage_start)
        return _failed_result(patient_id=patient_id, stage=PatientStage.NORMALIZING, error=str(exc))

    patient_index = PatientFactIndex(
        patient_id=patient_id,
        observations={obs.id: obs for obs in observations},
        medications={med.id: med for med in medications},
    )
    _stage_start = _mark_stage(stage_timings, PatientStage.NORMALIZING, _stage_start)

    # --- RULES_EVALUATED ---
    k_result = evaluate_k_high_risk(
        observations, medications, config=k_config, med_classes=med_classes, evaluated_at=now
    )
    validity_results = _evaluate_validity_metrics(patient_resource, observations, now=now)
    _stage_start = _mark_stage(stage_timings, PatientStage.RULES_EVALUATED, _stage_start)

    # --- EVIDENCE_RETRIEVAL --- (the passed-in `snapshot` only -- no live fetch)
    _stage_start = _mark_stage(stage_timings, PatientStage.EVIDENCE_RETRIEVAL, _stage_start)

    # --- AI_REASONING ---
    user_input = _build_model_a_input(
        patient_id=patient_id,
        observations=observations,
        medications=medications,
        adverse_reactions=adverse_reactions,
        rule_results=(k_result,),
        snapshot=snapshot,
    )
    try:
        claim_set = generate_claims(
            model_a, model_system_instruction=MODEL_A_SYSTEM_INSTRUCTION, user_input=user_input
        )
    except Exception as exc:  # noqa: BLE001 -- fail closed, never a crash or silent "no findings"
        _mark_stage(stage_timings, PatientStage.AI_REASONING, _stage_start)
        return _failed_result(
            patient_id=patient_id, stage=PatientStage.AI_REASONING, error=str(exc)
        )
    _stage_start = _mark_stage(stage_timings, PatientStage.AI_REASONING, _stage_start)

    # --- CITATION_CHECK / INDEPENDENT_REVIEW / FINAL_VALIDATION (per claim) ---
    findings: list[FindingResult] = []
    claim_verdicts: list[ClaimVerdict] = []
    cited_evidence_ids: set[str] = set()
    _citation_check_elapsed = 0.0
    _independent_review_elapsed = 0.0

    for claim in claim_set.claims:
        _claim_start = time.perf_counter()
        cur = _build_claim_under_review(
            claim, patient_index=patient_index, rule_results=(k_result,)
        )
        outcome = run_deterministic_layer(cur, snapshot=snapshot)
        _citation_check_elapsed += time.perf_counter() - _claim_start

        model_b_verdict: ModelBVerdict | None = None
        if not outcome.blocked:
            _review_start = time.perf_counter()
            packet = build_model_b_packet(
                cur, snapshot=snapshot, citation_results=outcome.citation_results
            )
            try:
                model_b_verdict = run_model_b(model_b, packet)
            except Exception as exc:  # noqa: BLE001 -- fail closed, never a crash or silent "no findings"
                _independent_review_elapsed += time.perf_counter() - _review_start
                if stage_timings is not None:
                    stage_timings[PatientStage.CITATION_CHECK.value] = _citation_check_elapsed
                    stage_timings[PatientStage.INDEPENDENT_REVIEW.value] = (
                        _independent_review_elapsed
                    )
                return _failed_result(
                    patient_id=patient_id,
                    stage=PatientStage.INDEPENDENT_REVIEW,
                    error=str(exc),
                )
            _independent_review_elapsed += time.perf_counter() - _review_start

        has_external_evidence = bool(claim.external_evidence)
        # `is_clinician_reviewed`'s `reviewed_by` concept is populated only by
        # the curated guideline pack (`app.evidence.guideline_pack`) -- an
        # openFDA/PubMed record simply has no such metadata key at all, so
        # applying the check to those tiers would misreport every regulatory/
        # literature citation as "pending review". Scope it to GUIDELINE tier
        # only, matching `app.gate.claim_gate.finalize_claim_verdict`'s own
        # docstring ("A `reviewed_by: PENDING` GUIDELINE record caps...").
        any_pending = any(
            (record := snapshot.get(ref.evidence_id)) is not None
            and record.tier == EvidenceTier.GUIDELINE
            and not is_clinician_reviewed(record)
            for ref in claim.external_evidence
        )

        verdict = finalize_claim_verdict(
            claim_type=claim.claim_type,
            external_evidence_required=claim.claim_type in _EXTERNAL_EVIDENCE_REQUIRED_TYPES,
            has_external_evidence=has_external_evidence,
            integrity_failures=outcome.integrity_failures,
            citation_results=outcome.citation_results,
            model_b_verdict=model_b_verdict,
            any_cited_evidence_pending_review=any_pending,
        )
        claim_verdicts.append(verdict)
        findings.append(
            FindingResult(
                claim=claim,
                verdict=verdict,
                citation_results=outcome.citation_results,
                model_b_verdict=model_b_verdict,
            )
        )
        cited_evidence_ids.update(ref.evidence_id for ref in claim.external_evidence)

    if stage_timings is not None:
        stage_timings[PatientStage.CITATION_CHECK.value] = _citation_check_elapsed
        stage_timings[PatientStage.INDEPENDENT_REVIEW.value] = _independent_review_elapsed
    _stage_start = time.perf_counter()

    # --- FINAL_VALIDATION -> PERSISTED ---
    terminal_status = derive_patient_status(
        claim_verdicts, stage=PatientStage.PERSISTED, commit_status=CommitStatus.COMMITTED
    )
    claims_payload = [
        (claim.claim_id, json.loads(claim.model_dump_json())) for claim in claim_set.claims
    ]
    evidence_payload = [
        (evidence_id, json.loads(record.model_dump_json()))
        for evidence_id in sorted(cited_evidence_ids)
        if (record := snapshot.get(evidence_id)) is not None
    ]
    try:
        final_summary = finalize_patient_result(
            repository,
            run_id=run_id,
            patient_id=patient_id,
            evidence_snapshot_id=snapshot.snapshot_id,
            stage=PatientStage.FINAL_VALIDATION,
            claims=claims_payload,
            evidence=evidence_payload,
            terminal_status=terminal_status,
        )
    except StorageError as exc:
        _mark_stage(stage_timings, PatientStage.FINAL_VALIDATION, _stage_start)
        return _failed_result(
            patient_id=patient_id, stage=PatientStage.FINAL_VALIDATION, error=str(exc)
        )
    # `finalize_patient_result` performs both validating/writing the final
    # artifacts (FINAL_VALIDATION) and flipping the terminal COMMITTED
    # marker (PERSISTED) in one atomic call (see `app.storage.two_phase`) --
    # there is no separate boundary to measure between the two, so the whole
    # call's elapsed time is attributed to FINAL_VALIDATION and PERSISTED is
    # recorded as the (near-instant) marker step immediately after it.
    _stage_start = _mark_stage(stage_timings, PatientStage.FINAL_VALIDATION, _stage_start)
    _mark_stage(stage_timings, PatientStage.PERSISTED, _stage_start)

    return PatientRunResult(
        patient_id=patient_id,
        summary=PatientRunSummary(
            status=final_summary.status,
            stage=final_summary.stage,
            commit_status=final_summary.commit_status,
        ),
        findings=tuple(findings),
        rule_results=(k_result,),
        validity_results=tuple(validity_results),
        timeline_events=_build_timeline(patient_index),
        error=None,
        patient_name=patient_name,
        normalized_observations=tuple(observations),
        normalized_medications=tuple(medications),
        normalized_adverse_reactions=tuple(adverse_reactions),
    )


def _mark_stage(stage_timings: dict[str, float] | None, stage: PatientStage, start: float) -> float:
    """Record elapsed wall-seconds for `stage` since `start` into
    `stage_timings` (a no-op when `None`) and return a fresh
    `time.perf_counter()` reading to use as the next stage's `start`.
    """
    checkpoint = time.perf_counter()
    if stage_timings is not None:
        stage_timings[stage.value] = checkpoint - start
    return checkpoint


def _failed_result(*, patient_id: str, stage: PatientStage, error: str) -> PatientRunResult:
    status = derive_patient_status((), stage=stage, commit_status=CommitStatus.FAILED, failed=True)
    return PatientRunResult(
        patient_id=patient_id,
        summary=PatientRunSummary(status=status, stage=stage, commit_status=CommitStatus.FAILED),
        findings=(),
        rule_results=(),
        validity_results=(),
        timeline_events=(),
        error=error,
    )


def _build_claim_under_review(
    claim: Claim,
    *,
    patient_index: PatientFactIndex,
    rule_results: tuple[RuleResult, ...],
) -> ClaimUnderReview:
    """Build the `ClaimUnderReview` for one claim. See module docstring for
    the asserted-fact extraction rationale."""
    asserted_observations: list[AssertedObservationValue] = []
    asserted_medications: list[AssertedMedication] = []

    for ref in claim.patient_evidence:
        if ref.resource_type == "Observation":
            obs = patient_index.observations.get(ref.resource_id)
            if obs is not None and isinstance(obs.value, NormalizedQuantity):
                asserted_observations.append(
                    AssertedObservationValue(
                        resource_id=ref.resource_id,
                        analyte=_ANALYTE_BY_CODE.get(obs.code, obs.display or obs.code),
                        value=obs.value.value,
                        unit=obs.value.unit,
                    )
                )
            elif obs is None:
                # Cites a resource id absent from this patient's own chart --
                # recorded (with a sentinel value) so the deterministic layer
                # still catches it as RESOURCE_NOT_FOUND, never silently
                # dropped from the review.
                asserted_observations.append(
                    AssertedObservationValue(
                        resource_id=ref.resource_id,
                        analyte="unknown",
                        value=Decimal(0),
                        unit="",
                    )
                )
        elif ref.resource_type == "MedicationRequest":
            med = patient_index.medications.get(ref.resource_id)
            ingredient = med.medication_display if med is not None else None
            asserted_medications.append(
                AssertedMedication(
                    resource_id=ref.resource_id, ingredient=ingredient or ref.resource_id
                )
            )

    return ClaimUnderReview(
        claim=claim,
        asserted_observations=tuple(asserted_observations),
        asserted_medications=tuple(asserted_medications),
        patient_index=patient_index,
        rule_results=rule_results,
    )


def _value_str(value: NormalizedQuantity | str | None) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, NormalizedQuantity):
        return f"{value.value} {value.unit}"
    return value


def _build_model_a_input(
    *,
    patient_id: str,
    observations: list[NormalizedObservation],
    medications: list[NormalizedMedicationOrder],
    adverse_reactions: list[NormalizedAdverseReaction],
    rule_results: tuple[RuleResult, ...],
    snapshot: EvidenceSnapshot,
) -> str:
    """Build Model A's user-input text from normalized facts + rule results
    + the snapshot's evidence regions. Deterministic (sorted by resource id)
    so the same patient/snapshot always produces byte-identical input."""
    lines: list[str] = [f"PATIENT_ID: {patient_id}", "", "NORMALIZED OBSERVATIONS:"]
    for obs in sorted(observations, key=lambda o: o.id):
        lines.append(
            f"- id={obs.id} code={obs.code} display={obs.display!r} status={obs.status.value} "
            f"value={_value_str(obs.value)} effective={obs.effective.source_string!r}"
        )

    lines.append("")
    lines.append("NORMALIZED MEDICATIONS:")
    for med in sorted(medications, key=lambda m: m.id):
        lines.append(
            f"- id={med.id} display={med.medication_display!r} status={med.status.value} "
            f"is_active_order={med.is_active_order}"
        )

    lines.append("")
    lines.append("ADVERSE REACTIONS:")
    for adr in adverse_reactions:
        lines.append(
            f"- kind={adr.kind.value} agent={adr.causative_agent!r} "
            f"manifestation={adr.manifestation!r}"
        )

    lines.append("")
    lines.append("RULE RESULTS:")
    for rule in rule_results:
        lines.append(
            f"- {rule.rule_id} v{rule.rule_version}: verdict={rule.verdict.value} "
            f"severity={rule.severity.value if rule.severity is not None else None} "
            f"rationale={rule.rationale}"
        )

    lines.append("")
    lines.append(f"EVIDENCE SNAPSHOT {snapshot.snapshot_id}:")
    for record in snapshot.records:
        lines.append(
            f"- evidence_id={record.id} tier={record.tier.value} title={record.title!r} "
            f"content={record.content!r}"
        )

    return "\n".join(lines)


def _build_timeline(patient_index: PatientFactIndex) -> tuple[str, ...]:
    events: list[str] = []
    for resource_id in sorted(patient_index.observations):
        obs = patient_index.observations[resource_id]
        events.append(
            f"observation {resource_id}: effective={obs.effective.source_string!r} "
            f"status={obs.status.value} value={_value_str(obs.value)}"
        )
    for resource_id in sorted(patient_index.medications):
        med = patient_index.medications[resource_id]
        events.append(
            f"medication {resource_id}: authored_on={med.authored_on.source_string!r} "
            f"status={med.status.value}"
        )
    return tuple(events)


def _age_years(birth_date: str | None, *, now: datetime) -> Decimal | None:
    if not birth_date:
        return None
    parts = birth_date.split("-")
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(p) for p in parts)
    except ValueError:
        return None
    years = now.year - year - ((now.month, now.day) < (month, day))
    return Decimal(years) if years >= 0 else None


def _sex(gender: str | None) -> str | None:
    return gender if gender in ("male", "female") else None


def _patient_display_name(patient_resource: dict[str, object]) -> str:
    """Best-effort human-readable name from a FHIR `Patient.name` array.

    Prefers the first entry's `text`; otherwise joins `given` + `family`.
    Returns `""` (never raises) if `Patient.name` is absent/malformed --
    the presentation layer treats an empty name as "unknown", never a
    fabricated placeholder.
    """
    names = patient_resource.get("name")
    if not isinstance(names, list) or not names:
        return ""
    first = names[0]
    if not isinstance(first, dict):
        return ""
    text = first.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    given = first.get("given")
    given_str = " ".join(g for g in given if isinstance(g, str)) if isinstance(given, list) else ""
    family = first.get("family")
    family_str = family if isinstance(family, str) else ""
    full = " ".join(part for part in (given_str, family_str) if part)
    return full


def _evaluate_validity_metrics(
    patient_resource: dict[str, object],
    observations: list[NormalizedObservation],
    *,
    now: datetime,
) -> tuple[ValidityResult, ...]:
    """Best-effort eGFR evaluation when age/sex/creatinine are all available.

    Never raises -- `ClinicalValidityEngine.evaluate` itself never raises,
    returning `INSUFFICIENT_DATA`/`INVALID` instead, so a demo patient
    missing `birthDate`/`gender` simply yields no validity result rather
    than failing the run.
    """
    creatinine_obs = latest_valid_observation(observations, code="2160-0")
    if creatinine_obs is None or not isinstance(creatinine_obs.value, NormalizedQuantity):
        return ()

    birth_date = patient_resource.get("birthDate")
    gender = patient_resource.get("gender")
    age_years = _age_years(birth_date if isinstance(birth_date, str) else None, now=now)
    sex = _sex(gender if isinstance(gender, str) else None)
    if age_years is None or sex is None:
        return ()

    creatinine_mg_dl = creatinine_obs.value.value if creatinine_obs.value.unit == "mg/dL" else None

    engine = build_default_engine()
    result = engine.evaluate(
        EGFR_METRIC_ID,
        {
            "age_years": age_years,
            "sex": sex,
            "serum_creatinine_mg_dl": creatinine_mg_dl,
        },
    )
    return (result,)
