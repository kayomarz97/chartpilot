"""§67 high-priority coverage ledger: 22 load-bearing safety invariants.

This module is deliberately a LEDGER, not a fresh test suite: most of these
22 invariants already have a dedicated unit test somewhere in `tests/unit/`
or elsewhere in `tests/adversarial/` (Phases 2-15). Re-asserting all 22 in
full here would just duplicate that coverage. Instead, each item is either:

  (a) IMPORTED-AND-CALLED: this module imports the real production function
      and re-asserts the invariant itself, inline, using the SAME code path
      the dedicated test uses -- not a paraphrase of it.
  (b) INLINE: a short, self-contained assertion against real app code that
      has no single dedicated test elsewhere (or where re-deriving it here
      cheaply is more legible than a cross-reference).
  (c) REFERENCED: a pointer to the existing `tests/unit/...::test_...`
      function that already covers it. `_assert_test_function_exists` makes
      every (c) reference a REAL, executed assertion -- it greps the
      referenced test file's source for `def <function_name>(` and fails
      this module if that function is ever renamed or deleted, so a (c)
      reference can never silently rot into a dangling pointer.

Items 1-10 below are the ones spec'd by name for Phase 15; items 11-22 round
out the §67 high-priority set with the other load-bearing invariants already
proven by Phases 2-14's own test suites.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.agent.models import ClaimType, ExternalEvidenceRef
from app.citation.models import CitationVerdict
from app.citation.verifier import offsets_still_valid, verify_citation
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier, Jurisdiction
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.gate.patient_state import derive_patient_status
from app.normalize.medication import normalize_medication_order
from app.normalize.observation import normalize_observation
from app.review.corruption import (
    citation_span_absent,
    nonexistent_resource_id,
    numeric_mismatch,
)
from app.review.deterministic import run_deterministic_layer
from app.review.packet import build_model_b_packet
from app.rules.models import RuleVerdict
from app.rules.potassium import evaluate_k_high_risk
from app.tasks.models import BudgetCounters, ExecutionBudget, RunTask
from app.tasks.orchestrator import process_patient
from app.tasks.queue import InMemoryTaskQueue
from app.tasks.storage import InMemoryCheckpointStore
from tests.adversarial.test_fabrication_rejected import build_clean_patient_a_base
from tests.adversarial.test_prompt_injection_invariant import build_projection

_UNIT_TESTS_DIR = Path(__file__).resolve().parents[1] / "unit"
_NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _assert_test_function_exists(test_file: str, function_name: str) -> None:
    """Fail this module if the referenced `tests/unit/<test_file>::
    <function_name>` no longer exists -- turns every (c) reference below
    into a real, checked assertion rather than a comment that can rot."""
    source = (_UNIT_TESTS_DIR / test_file).read_text(encoding="utf-8")
    assert f"def {function_name}(" in source, (
        f"§67 coverage reference is stale: tests/unit/{test_file} no longer "
        f"defines {function_name}() -- update this ledger or restore the test."
    )


# ---------------------------------------------------------------------------
# Items 1-10: named explicitly for Phase 15, re-asserted here with real code.
# ---------------------------------------------------------------------------


def test_67_01_entered_in_error_does_not_fire_the_k_rule() -> None:
    """§67 item 1: a retracted (entered-in-error) potassium value must never
    fire K_HIGH_RISK_001, no matter how critical the retracted number was."""
    obs = normalize_observation(
        {
            "resourceType": "Observation",
            "id": "k-eie",
            "status": "entered-in-error",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
            "valueQuantity": {"value": 9.9, "unit": "mmol/L"},
            "effectiveDateTime": "2025-05-30T10:00:00Z",
        }
    )
    med = normalize_medication_order(
        {
            "resourceType": "MedicationRequest",
            "id": "m-eie",
            "status": "active",
            "medicationCodeableConcept": {"text": "Lisinopril 10 MG Oral Tablet"},
        }
    )
    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)
    assert result.verdict != RuleVerdict.FIRED
    _assert_test_function_exists(
        "test_potassium_rule.py", "test_entered_in_error_potassium_does_not_fire"
    )


def test_67_02_unknown_unit_blocks_the_rule() -> None:
    """§67 item 2: a potassium value on an unregistered/unconvertible unit
    can never be safely compared to the critical band -- the rule must
    report INSUFFICIENT_DATA, never FIRED, never NOT_FIRED (which would
    imply the value was safely known to be non-critical)."""
    obs = normalize_observation(
        {
            "resourceType": "Observation",
            "id": "k-unit",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
            "valueQuantity": {"value": 6.2, "unit": "banana"},
            "effectiveDateTime": "2025-05-30T10:00:00Z",
        }
    )
    med = normalize_medication_order(
        {
            "resourceType": "MedicationRequest",
            "id": "m-unit",
            "status": "active",
            "medicationCodeableConcept": {"text": "Lisinopril 10 MG Oral Tablet"},
        }
    )
    result = evaluate_k_high_risk([obs], [med], evaluated_at=_NOW)
    assert result.verdict == RuleVerdict.INSUFFICIENT_DATA
    _assert_test_function_exists(
        "test_potassium_rule.py", "test_unknown_unit_potassium_does_not_fire"
    )


def test_67_03_medication_active_is_not_adherence() -> None:
    """§67 item 3: `MedicationRequest.status == active` means a prescriber's
    order is active -- it is NOT proof the patient is taking the drug.
    `NormalizedMedicationOrder` must carry no `is_taking`/adherence field of
    any kind (spec §31)."""
    order = normalize_medication_order(
        {
            "resourceType": "MedicationRequest",
            "id": "m-adherence",
            "status": "active",
            "medicationCodeableConcept": {"text": "Lisinopril 10 MG Oral Tablet"},
        }
    )
    assert order.is_active_order is True
    for forbidden in ("is_taking", "adherence", "is_adherent", "taking"):
        assert not hasattr(order, forbidden)
    _assert_test_function_exists(
        "test_medication.py", "test_active_order_is_active_but_exposes_no_adherence_field"
    )


def test_67_04_fabricated_resource_value_and_citation_are_rejected() -> None:
    """§67 items 7-9: a fabricated resource id, a fabricated numeric value,
    and a fabricated citation span each independently block the
    deterministic layer for a real Patient A claim -- see
    `tests/adversarial/test_fabrication_rejected.py` for the full REJECTED-
    verdict assertions (including the "Model B still can't override it"
    proof); here we re-confirm the deterministic layer itself catches all
    three starting from the SAME clean base."""
    cur, snapshot = build_clean_patient_a_base()
    for corrupt in (nonexistent_resource_id, numeric_mismatch, citation_span_absent):
        corrupted_cur, corrupted_snapshot = corrupt(cur, snapshot)
        outcome = run_deterministic_layer(corrupted_cur, snapshot=corrupted_snapshot)
        assert outcome.blocked is True, corrupt.__name__
    _assert_test_function_exists("test_review_integrity.py", "test_numeric_mismatch_detected")
    _assert_test_function_exists(
        "test_review_integrity.py", "test_nonexistent_observation_resource_id_detected"
    )


def test_67_05_injection_invariant_holds() -> None:
    """§67 item 5: re-import and re-call the actual §53.2 injection-invariant
    projection (`tests.adversarial.test_prompt_injection_invariant.
    build_projection`) rather than re-implementing it -- the benign and the
    two adversarial-note runs must project to byte-identical deterministic
    output. See that module for the full marquee test + docstring."""
    benign = build_projection("patient_a_note_benign.json")
    injection = build_projection("patient_a_note_injection.json")
    assert benign == injection


def test_67_06_duplicate_task_does_not_double_process() -> None:
    """§67 item 6: enqueueing the same (run_id, patient_id) task twice is
    deduped at the queue -- a retried/duplicated Cloud Tasks delivery must
    never cause the pipeline to process the same patient twice."""
    queue = InMemoryTaskQueue()
    first = RunTask(run_id="run-coverage", patient_id="pat-coverage", attempt=0)
    second = RunTask(run_id="run-coverage", patient_id="pat-coverage", attempt=1)

    assert queue.enqueue(first) is True
    assert queue.enqueue(second) is False
    assert len(queue.tasks) == 1
    _assert_test_function_exists("test_task_queue.py", "test_duplicate_task_name_is_deduped")


def test_67_07_budget_exceeded_yields_timed_out() -> None:
    """§67 item 7 (orchestration half): exhausting the execution budget
    mid-run must terminate the patient at TIMED_OUT, at the last completed
    stage -- never silently reported as PERSISTED/COMPLETED."""
    store = InMemoryCheckpointStore()

    def bump_model_calls(task: RunTask, counters: BudgetCounters) -> None:
        counters.model_calls += 2

    budget = ExecutionBudget(
        max_wall_clock_s=1_000_000.0,
        max_stage_iterations=100,
        max_model_calls=1,
        max_evidence_calls=100,
        max_fhir_pages=100,
        max_retries=3,
    )
    task = RunTask(run_id="run-coverage-timeout", patient_id="pat-coverage-timeout", attempt=0)
    result = process_patient(
        task,
        store=store,
        budget=budget,
        stage_runners={PatientStage.FETCHING: bump_model_calls},
        clock=lambda: _NOW,
    )
    assert result.status == PatientStatus.TIMED_OUT
    assert result.current_stage != PatientStage.PERSISTED
    _assert_test_function_exists(
        "test_orchestrator.py", "test_budget_exceeded_marks_timed_out_at_last_completed_stage"
    )


def test_67_08_mixed_verdicts_persisted_committed_yields_partial() -> None:
    """§67 item 8: a run that reaches PERSISTED+COMMITTED but whose claim
    verdicts are a mix of VERIFIED and REJECTED/UNVERIFIABLE (no
    review-triggering verdict present) must report PARTIAL, never
    COMPLETED -- a partially-verified run is not silently a success."""
    status = derive_patient_status(
        [ClaimVerdict.VERIFIED, ClaimVerdict.REJECTED],
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.PARTIAL
    _assert_test_function_exists(
        "test_patient_state.py", "test_mix_of_verified_and_rejected_persisted_committed_is_partial"
    )


def test_67_09_changed_snapshot_invalidates_offsets() -> None:
    """§67 item 9: a citation's computed offsets are pinned to the exact
    evidence content they were computed against (`artifact_content_hash`).
    If the underlying record's content changes (a refreshed snapshot),
    `offsets_still_valid` must report False -- stale offsets are never
    silently reused."""
    original_content = "Some content that must not silently drift."
    record = EvidenceRecord(
        id="cov-1",
        tier=EvidenceTier.LITERATURE,
        title="Coverage Record",
        publisher="Test Publisher",
        jurisdiction=Jurisdiction.US_FDA,
        publication_date="2024-01-01",
        version="1",
        content=original_content,
        content_hash=content_hash(original_content),
        source_url="https://example.invalid/coverage",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        metadata={},
    )
    snapshot = EvidenceSnapshot(
        snapshot_id="snap-coverage",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        records=(record,),
        manifest_hash="deadbeef",
    )
    ref = ExternalEvidenceRef(evidence_id="cov-1", verbatim_supporting_span=original_content)
    result = verify_citation(ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT)
    assert result.verdict == CitationVerdict.VERIFIED_SPAN

    changed_content = "Completely different content after a snapshot refresh."
    changed_record = record.model_copy(
        update={"content": changed_content, "content_hash": content_hash(changed_content)}
    )
    assert offsets_still_valid(result, changed_record) is False
    _assert_test_function_exists(
        "test_citation_verifier.py", "test_offsets_still_valid_false_for_changed_content"
    )


def test_67_10_model_b_gets_a_full_region_not_just_the_span() -> None:
    """§67 item 10: the blinded packet handed to Model B carries the WHOLE
    cited evidence record's content, not merely Model A's chosen span --
    otherwise Model B could never catch a span that misrepresents its
    surrounding context (spec §21.2)."""
    cur, snapshot = build_clean_patient_a_base()
    outcome = run_deterministic_layer(cur, snapshot=snapshot)
    packet = build_model_b_packet(cur, snapshot=snapshot, citation_results=outcome.citation_results)

    assert len(packet.evidence_regions) == 1
    region = packet.evidence_regions[0]
    cited_record = snapshot.get(cur.claim.external_evidence[0].evidence_id)
    assert cited_record is not None
    assert region.full_region_text == cited_record.content
    assert len(region.full_region_text) > len(
        cur.claim.external_evidence[0].verbatim_supporting_span
    )
    _assert_test_function_exists(
        "test_review_packet.py", "test_packet_evidence_region_is_the_full_record_not_just_the_span"
    )


# ---------------------------------------------------------------------------
# Items 11-22: the rest of the §67 high-priority set, REFERENCED against
# their existing dedicated tests (option c). Each reference is a real,
# executed assertion via `_assert_test_function_exists` -- not a comment.
# ---------------------------------------------------------------------------

_REFERENCED_COVERAGE: tuple[tuple[str, str, str], ...] = (
    (
        "corrected/amended status supersedes final at the same clinical instant",
        "test_status_supersession.py",
        "test_same_instant_prefers_corrected_over_final",
    ),
    (
        "a retracted (entered-in-error/cancelled) value is never returned as "
        "the current finding, even as the only candidate",
        "test_status_supersession.py",
        "test_retracted_value_never_returned_even_as_only_candidate",
    ),
    (
        "a citation span occurring more than once is ambiguous and can only "
        "ever FLAG_FOR_REVIEW, never silently VERIFIED_SPAN",
        "test_citation_verifier.py",
        "test_span_occurring_twice_flags_for_review",
    ),
    (
        "a tampered evidence artifact (recomputed content hash mismatch) "
        "hard-REJECTs at Gate 2, before span matching is even attempted",
        "test_citation_verifier.py",
        "test_content_hash_mismatch_rejects",
    ),
    (
        "a GUIDELINE_RECOMMENDATION claim citing a LITERATURE-tier record is "
        "a hard tier violation (§12A.1), never silently accepted",
        "test_citation_verifier.py",
        "test_guideline_claim_citing_literature_record_rejects_tier_violation",
    ),
    (
        "a patient-fact integrity failure forces REJECTED even if Model B "
        "would have accepted the claim",
        "test_claim_gate.py",
        "test_integrity_failure_forces_rejected_even_if_model_b_accepts",
    ),
    (
        "a hard citation REJECT forces REJECTED even if Model B would have "
        "accepted the claim (§65.4, the same invariant this phase's "
        "fabrication-rejected tests re-prove end to end)",
        "test_claim_gate.py",
        "test_citation_reject_forces_rejected_even_if_model_b_accepts",
    ),
    (
        "a `reviewed_by: PENDING` guideline record caps a claim at "
        "PARTIALLY_VERIFIED -- it can never reach full VERIFIED until that "
        "evidence itself clears human review",
        "test_claim_gate.py",
        "test_pending_review_evidence_caps_at_partially_verified",
    ),
    (
        "a claim type that requires external evidence but was given none is "
        "UNVERIFIABLE, never silently VERIFIED",
        "test_claim_gate.py",
        "test_missing_required_external_evidence_yields_unverifiable",
    ),
    (
        "a two-phase commit fault injected between the claims write and the "
        "summary write leaves the summary PREPARING -- never falsely "
        "reported COMMITTED",
        "test_two_phase.py",
        "test_fault_injected_between_writes_leaves_summary_preparing",
    ),
    (
        "reconciling an interrupted (PREPARING) summary flags NEEDS_REDO, "
        "never silently treats it as committed",
        "test_two_phase.py",
        "test_reconcile_on_interrupted_summary_flags_needs_redo_never_committed",
    ),
    (
        "Model A's structured-output response schema has no character-offset "
        "field of any kind -- a citation offset is never trusted from the "
        "model, only computed downstream over trusted stored text",
        "test_agent_claims.py",
        "test_claim_response_schema_has_no_offset_field",
    ),
)


def test_67_11_through_22_referenced_coverage_is_present_and_current() -> None:
    """§67 items 11-22: each entry in `_REFERENCED_COVERAGE` names one
    high-priority invariant already proven by a dedicated `tests/unit/` test.
    This is a genuine ledger check, not a stub: it fails if any referenced
    test function is ever renamed or removed without this ledger being
    updated to match."""
    assert len(_REFERENCED_COVERAGE) == 12
    for _description, test_file, function_name in _REFERENCED_COVERAGE:
        _assert_test_function_exists(test_file, function_name)


def test_67_ledger_covers_exactly_twenty_two_items() -> None:
    """Structural sanity: 10 inline (a)/(b) items above + 12 referenced (c)
    items == the full 22-item §67 high-priority set this module documents."""
    inline_item_count = 10
    referenced_item_count = len(_REFERENCED_COVERAGE)
    assert inline_item_count + referenced_item_count == 22
