"""Score a `Candidate` against the active artifact, and a concrete, hermetic
default `ScoreFn` built from the FROZEN §22 corruption benchmark
(`app.review.corruption`) plus held-out clinician-labeled cases.

`app.review.corruption.py` is never imported here in a way that mutates it
-- `build_benchmark_score_fn` only ever CALLS `measure_suite`/reads
`SET_M_CORRUPTIONS`, exactly like `tests/unit/test_corruption_suite.py`
does; the benchmark itself stays exactly as frozen as it always was.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from app.agent.models import Claim, ClaimType, ExternalEvidenceRef, PatientEvidenceRef
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier, Jurisdiction
from app.improve.models import (
    Candidate,
    Dataset,
    EvaluationResult,
    Metrics,
    case_is_automated_flag,
)
from app.normalize.medication import MedicationOrderStatus, NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation, ObservationStatus
from app.normalize.temporal import parse_fhir_datetime
from app.normalize.units import NormalizedQuantity
from app.review.corruption import (
    SET_M_CORRUPTIONS,
    CorruptionCase,
    CorruptionSet,
    build_set_d_cases,
    build_set_m_cases,
    measure_suite,
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
)

__all__ = [
    "ScoreFn",
    "compare_metrics",
    "evaluate_candidate",
    "build_benchmark_score_fn",
    "clinician_agreement_from_holdout",
]

#: Scores an artifact VALUE (e.g. a candidate or the active Model-A prompt
#: text) against the frozen benchmark + the holdout clinician cases.
#: Injectable so tests stay deterministic and hermetic (no LLM, no network)
#: -- see `build_benchmark_score_fn` for the concrete default.
ScoreFn = Callable[[str], Metrics]


def compare_metrics(before: Metrics, after: Metrics) -> tuple[bool, bool]:
    """Compare `after` to `before` on all four benchmark axes and return
    `(improved, regressed)`.

    Explicit ordering (spec):
      - `set_d_blocked`, `set_m_caught`, `clinician_agreement`: HIGHER is
        better -- catching more corruptions / agreeing with more clinicians
        is strictly good.
      - `false_reject`: LOWER is better -- rejecting a genuinely correct
        claim is a cost, not a benefit.

    `regressed` is True the moment ANY axis moves in the worse direction,
    even if others improve (an improvement on one axis never buys tolerance
    for a regression on another). `improved` is True iff AT LEAST ONE axis
    moves in the better direction. A candidate that ties on every axis is
    therefore neither improved nor regressed -- `evaluate_candidate` treats
    that as a reject (no reason to promote a no-op).
    """
    improved = (
        after.set_d_blocked > before.set_d_blocked
        or after.set_m_caught > before.set_m_caught
        or after.clinician_agreement > before.clinician_agreement
        or after.false_reject < before.false_reject
    )
    regressed = (
        after.set_d_blocked < before.set_d_blocked
        or after.set_m_caught < before.set_m_caught
        or after.clinician_agreement < before.clinician_agreement
        or after.false_reject > before.false_reject
    )
    return improved, regressed


def evaluate_candidate(
    candidate: Candidate, *, active_value: str, score_fn: ScoreFn
) -> EvaluationResult:
    """Score `candidate.new_value` against `active_value` via `score_fn` and
    decide accept/reject. `accept = improved and not regressed` -- strict
    improvement on at least one axis, zero regression on any (see
    `compare_metrics`)."""
    metrics_before = score_fn(active_value)
    metrics_after = score_fn(candidate.new_value)
    improved, regressed = compare_metrics(metrics_before, metrics_after)
    accept = improved and not regressed
    if accept:
        detail = "accepted: strict improvement on at least one axis, no regression on any"
    elif regressed:
        detail = "rejected: regression on at least one axis"
    else:
        detail = "rejected: no improvement on any axis (tie against the active value)"
    return EvaluationResult(
        accept=accept,
        improved=improved,
        regressed=regressed,
        metrics_before=metrics_before,
        metrics_after=metrics_after,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# The concrete default ScoreFn -- hermetic, no LLM, no network.
# ---------------------------------------------------------------------------

_SUPPORTING_SPAN = "Hyperkalemia has been reported with concomitant use of this medication class."
_RECORD_CONTENT = (
    "WARNINGS AND PRECAUTIONS: Hyperkalemia has been reported with concomitant use of this "
    "medication class. Monitor serum potassium periodically in at-risk patients."
)
_FIXTURE_INSTANT = datetime(2024, 1, 1, tzinfo=UTC)


def _build_reference_fixture() -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """A fixed, hand-authored clean `(ClaimUnderReview, EvidenceSnapshot)`
    pair satisfying `app.review.corruption`'s documented preconditions for a
    "clean base" (mirrors `tests/unit/test_corruption_suite.py`'s
    `_build_clean_base`) -- used ONLY to replay the frozen §22 corruption
    suite. Synthetic; never derived from any real patient.
    """
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
        retrieved_at=_FIXTURE_INSTANT,
        metadata={},
    )
    snapshot = EvidenceSnapshot(
        snapshot_id="improve-benchmark-snap-1",
        created_at=_FIXTURE_INSTANT,
        records=(record,),
        manifest_hash="deadbeef",
    )
    claim = Claim(
        claim_id="improve-benchmark-claim-1",
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
        patient_id="improve-benchmark-patient",
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


def _run_deterministic(cur: ClaimUnderReview, snapshot: EvidenceSnapshot) -> DeterministicOutcome:
    """Adapts `run_deterministic_layer`'s keyword-only `snapshot` to
    `app.review.corruption.DeterministicRunner`'s positional-`snapshot`
    shape (mirrors `tests/unit/test_corruption_suite.py`'s
    `_deterministic_runner`)."""
    return run_deterministic_layer(cur, snapshot=snapshot)


def _reference_model_b(name: str, packet: ModelBPacket) -> ModelBVerdict:
    """Hermetic Model-B stand-in (never a real Gemini call, never touches
    the network): rejects every named Set M corruption scenario, accepts
    everything else -- i.e. a perfect reviewer, so `set_m_caught`/
    `false_reject` measure the deterministic layer + frozen-suite SHAPE,
    not any particular model's quirks."""
    del packet  # the blinded packet is not needed by this fixed stand-in
    if name in SET_M_CORRUPTIONS:
        return ModelBVerdict(
            finding=ReviewFinding.CONTRADICTED,
            should_reject=True,
            rationale="reference stand-in: caught",
        )
    return ModelBVerdict(
        finding=ReviewFinding.SUPPORTED, should_reject=False, rationale="reference stand-in: clean"
    )


def clinician_agreement_from_holdout(dataset_holdout: Dataset) -> float:
    """Fraction of LABELED holdout cases where the clinician's action
    agrees with the automated outcome: a CONFIRM agrees iff the automated
    layer did NOT flag the case; an OVERRIDE/CORRECT agrees iff it DID.

    An unlabeled case (`clinician_action is None`) is excluded from both the
    numerator and denominator -- it carries no ground truth to agree or
    disagree with. No labeled cases at all -> trivially `1.0` (mirrors
    `app.review.corruption.release_threshold_met`'s empty-set convention:
    an axis with nothing to measure imposes no penalty).

    Public (not `_`-prefixed): also reused by `app.improve.evaluator_live.
    build_live_pipeline_score_fn` so the live `ScoreFn`'s `clinician_
    agreement` axis is computed by the exact same rule as this hermetic
    default's, rather than a second, potentially-drifting copy.
    """
    agreed = 0
    total = 0
    for case in dataset_holdout.cases:
        if case.clinician_action is None:
            continue
        total += 1
        flagged = case_is_automated_flag(case)
        action = case.clinician_action.lower()
        agrees = (action == "confirm" and not flagged) or (
            action in {"override", "correct"} and flagged
        )
        if agrees:
            agreed += 1
    return (agreed / total) if total else 1.0


def build_benchmark_score_fn(dataset_holdout: Dataset) -> ScoreFn:
    """The concrete default `ScoreFn`: measures the frozen §22 corruption
    suite (`app.review.corruption.measure_suite`) via a fixed hermetic
    fixture + a fixed hermetic Model-B stand-in, plus `clinician_agreement`
    computed once from `dataset_holdout`.

    IMPORTANT -- read before wiring this up anywhere: the returned function
    is intentionally a function of the FROZEN benchmark and the (fixed,
    already-recorded) holdout dataset ONLY. It does NOT re-run Model A or
    Model B against the candidate `value` it is called with, because doing
    so would require a real network call, and this package's hermetic test
    suite (`--disable-socket`, no live Gemini) must never make one.
    Concretely: calling the returned function with two different `value`
    strings yields IDENTICAL `Metrics` -- the current, frozen-suite status
    quo. Combined with `evaluate_candidate`'s "accept only on strict
    improvement" rule, this means THIS DEFAULT can never, by itself, cause a
    candidate to be accepted (a tie is always a reject) -- which is the
    correct, safe behavior for a scorer that cannot yet actually evaluate
    what a new prompt/ranking would do. A live-capable `ScoreFn` that
    genuinely re-evaluates the candidate against Model A/B is a separate,
    explicitly out-of-scope-for-this-phase component (see
    `app.api.composition.get_improve_score_fn`'s docstring); tests inject
    their OWN `ScoreFn` fakes that DO vary with `value` to exercise
    `evaluate_candidate`'s accept/reject logic.
    """
    cur, snapshot = _build_reference_fixture()
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
    agreement = clinician_agreement_from_holdout(dataset_holdout)

    def score(value: str) -> Metrics:
        del value  # see docstring: cannot vary without a live model call
        report = measure_suite(
            set_d=set_d_cases,
            set_m=set_m_cases,
            control=control_cases,
            run_deterministic=_run_deterministic,
            run_model_b=_reference_model_b,
        )
        return Metrics(
            set_d_blocked=report.set_d_blocked_pre_b,
            set_m_caught=report.set_m_caught,
            false_reject=report.false_reject,
            clinician_agreement=agreement,
        )

    return score
