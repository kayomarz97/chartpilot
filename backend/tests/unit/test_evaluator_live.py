"""Tests for `app.improve.evaluator_live.build_live_pipeline_score_fn` -- the
LIVE `ScoreFn` factory, driven entirely by a fake `run_pipeline` callable so
this module stays hermetic (no network, no real Gemini/`run_patient` call).

The PRIMARY objective is the review-survival rate (cited findings whose
citations all verify AND whose Model-B verdict is `SUPPORTED`/not
`should_reject`, divided by all cited findings); the citation verified-span
rate is a GUARD axis. See `app.improve.evaluator_live`'s module docstring
for why (baseline citation-span rate is saturated at 100%, review-survival
is the axis with real headroom).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.agent.models import Claim, ClaimType
from app.citation.models import CitationResult, CitationVerdict
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.improve.cycle import run_improvement_cycle
from app.improve.evaluator import evaluate_candidate
from app.improve.evaluator_live import build_live_pipeline_score_fn
from app.improve.models import Candidate, Dataset, ImproveTarget, Metrics, TrainingCase
from app.improve.promote import FilePromotionLedger
from app.pipeline.models import FindingResult, PatientRunResult, PatientRunSummary
from app.review.models import ModelBVerdict, ReviewFinding

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _citation(verdict: CitationVerdict, *, evidence_id: str) -> CitationResult:
    return CitationResult(
        evidence_id=evidence_id,
        snapshot_id="snap-1",
        verdict=verdict,
        gates=(),
        raw_span="span text",
        normalized_span="span text",
        computed_start_offset=0 if verdict == CitationVerdict.VERIFIED_SPAN else None,
        computed_end_offset=9 if verdict == CitationVerdict.VERIFIED_SPAN else None,
        artifact_content_hash="hash",
    )


def _claim(claim_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        claim_type=ClaimType.PATIENT_SPECIFIC_INFERENCE,
        statement="statement text",
        patient_evidence=[],
        external_evidence=[],
        rationale="rationale text",
    )


def _model_b(finding: ReviewFinding, *, should_reject: bool) -> ModelBVerdict:
    return ModelBVerdict(finding=finding, should_reject=should_reject, rationale="test verdict")


#: A "clean" Model-B verdict: SUPPORTED and not flagged for rejection --
#: the only verdict `_survives_review` (app.improve.evaluator_live) accepts.
_SUPPORTED = _model_b(ReviewFinding.SUPPORTED, should_reject=False)
#: An "unclean" Model-B verdict: a real finding a clinician would want
#: flagged -- fails `_survives_review` regardless of its citations.
_OVERSTATED_REJECTED = _model_b(ReviewFinding.OVERSTATED, should_reject=True)


def _finding(
    claim_id: str,
    verdicts: list[CitationVerdict],
    model_b_verdict: ModelBVerdict | None = None,
) -> FindingResult:
    return FindingResult(
        claim=_claim(claim_id),
        verdict=ClaimVerdict.VERIFIED,
        citation_results=tuple(
            _citation(v, evidence_id=f"{claim_id}-ev-{i}") for i, v in enumerate(verdicts)
        ),
        model_b_verdict=model_b_verdict,
    )


def _fabricate_result(patient_id: str, findings: list[FindingResult]) -> PatientRunResult:
    return PatientRunResult(
        patient_id=patient_id,
        summary=PatientRunSummary(
            status=PatientStatus.COMPLETED,
            stage=PatientStage.PERSISTED,
            commit_status=CommitStatus.COMMITTED,
        ),
        findings=tuple(findings),
        rule_results=(),
        validity_results=(),
        timeline_events=(),
    )


# --------------------------------------------------------------------------
# build_live_pipeline_score_fn: basic scoring behavior
# --------------------------------------------------------------------------


def test_higher_review_survival_rate_scores_strictly_higher_on_the_primary_axis() -> None:
    """The PRIMARY axis is review-survival, not the citation-span rate: two
    patients whose only difference is Model B's verdict (citations are
    VERIFIED_SPAN in both cases) must move `set_d_blocked`/`false_reject`
    but leave the guard axis (`set_m_caught`) untouched."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        model_b = _SUPPORTED if instruction == "better prompt" else _OVERSTATED_REJECTED
        finding = _finding("c1", [CitationVerdict.VERIFIED_SPAN], model_b)
        return _fabricate_result(patient_id, [finding])

    score_fn = build_live_pipeline_score_fn(
        benchmark=("patient-a", "patient-b"), run_pipeline=run_pipeline
    )

    before = score_fn("")
    after = score_fn("better prompt")

    assert isinstance(before, Metrics)
    assert isinstance(after, Metrics)
    assert after.set_d_blocked > before.set_d_blocked
    assert after.false_reject < before.false_reject
    # citation-span rate (the guard) is unaffected: every citation in both
    # runs is VERIFIED_SPAN.
    assert after.set_m_caught == before.set_m_caught == 10_000


def test_empty_candidate_prompt_resolves_to_none_instruction() -> None:
    """`""` is `run_improvement_cycle`'s sentinel for "nothing promoted
    yet" -- it must reach `run_pipeline` as `None` (run_patient's own
    "use the pinned default" sentinel), never a literal empty string."""
    seen: list[str | None] = []

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        seen.append(instruction)
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    score_fn("")

    assert seen == [None]


def test_non_empty_candidate_prompt_is_passed_through_verbatim() -> None:
    seen: list[str | None] = []

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        seen.append(instruction)
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    score_fn("a candidate prompt")

    assert seen == ["a candidate prompt"]


def test_zero_total_citations_scores_a_neutral_full_rate_on_both_axes() -> None:
    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        return _fabricate_result(patient_id, [_finding("c1", [], None)])

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    metrics = score_fn("anything")

    assert metrics.set_d_blocked == 10_000
    assert metrics.false_reject == 0
    assert metrics.set_m_caught == 10_000


def test_zero_cited_findings_patient_does_not_crash_and_contributes_neutrally() -> None:
    """A benchmark patient with no cited findings at all (e.g. every claim
    was purely a patient-fact restatement with no external evidence) must
    neither raise nor drag the pooled rate down -- it contributes `(0, 0)`
    to both the numerator and denominator, i.e. it is simply excluded from
    the pool, not treated as a failing `0.0` rate."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        if patient_id == "patient-empty":
            return _fabricate_result(patient_id, [_finding("c-empty", [], None)])
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(
        benchmark=("patient-empty", "patient-b"), run_pipeline=run_pipeline
    )
    metrics = score_fn("x")  # must not raise, must not divide by zero

    # Only patient-b contributes to the pool: 1/1 survives, 1/1 verifies.
    assert metrics.set_d_blocked == 10_000
    assert metrics.false_reject == 0
    assert metrics.set_m_caught == 10_000


def test_clinician_agreement_defaults_to_neutral_constant_without_holdout() -> None:
    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    metrics = score_fn("x")

    assert metrics.clinician_agreement == 1.0


def test_clinician_agreement_uses_the_holdout_dataset_when_given() -> None:
    holdout = Dataset(
        cases=(
            TrainingCase(
                patient_id="p1",
                claim_id="c1",
                claim_type="patient_fact",
                verdict="VERIFIED",
                citation_verdicts=(),
                model_b_should_reject=False,
                revision_attempts=0,
                clinician_action="override",  # disagrees: not flagged, but overridden
            ),
        )
    )

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(
        benchmark=("patient-a",), run_pipeline=run_pipeline, dataset_holdout=holdout
    )
    metrics = score_fn("x")

    assert metrics.clinician_agreement == 0.0


def test_never_touches_the_network() -> None:
    """Hermeticity smoke test (mirrors `app.improve.evaluator`'s
    `test_build_benchmark_score_fn_never_touches_the_network`): a fake
    `run_pipeline` never opens a socket, so this must not raise under
    `pytest-socket`'s `--disable-socket`."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        return _fabricate_result(
            patient_id, [_finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED)]
        )

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    score_fn("anything")  # must not raise


# --------------------------------------------------------------------------
# Through evaluate_candidate: an improving/regressing candidate is
# genuinely accepted/rejected by the live score fn.
# --------------------------------------------------------------------------


def test_evaluate_candidate_accepts_an_improving_candidate_through_the_live_score_fn() -> None:
    """A candidate that yields MORE Model-B-SUPPORTED cited findings (with
    the citation-span guard unchanged) scores strictly higher on the
    primary axis and is genuinely ACCEPTED by `evaluate_candidate`."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        model_b = _SUPPORTED if instruction == "better prompt" else _OVERSTATED_REJECTED
        finding = _finding("c1", [CitationVerdict.VERIFIED_SPAN], model_b)
        return _fabricate_result(patient_id, [finding])

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    candidate = Candidate(
        target=ImproveTarget.MODEL_A_PROMPT, new_value="better prompt", rationale="r"
    )

    result = evaluate_candidate(candidate, active_value="", score_fn=score_fn)

    assert result.accept is True
    assert result.improved is True
    assert result.regressed is False


def test_evaluate_candidate_rejects_a_candidate_that_drops_the_citation_span_guard() -> None:
    """A candidate that only changes the citation-span rate (Model B is
    never run either side) moves the GUARD axis (`set_m_caught`) but ties
    on the primary axis -- `evaluate_candidate` must still reject it,
    proving the guard alone can block acceptance."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        verdicts = (
            [CitationVerdict.VERIFIED_SPAN, CitationVerdict.REJECT]
            if instruction == "worse prompt"
            else [CitationVerdict.VERIFIED_SPAN, CitationVerdict.VERIFIED_SPAN]
        )
        finding = _finding("c1", verdicts, None)
        return _fabricate_result(patient_id, [finding])

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)
    candidate = Candidate(
        target=ImproveTarget.MODEL_A_PROMPT, new_value="worse prompt", rationale="r"
    )

    # active_value non-empty ("already active") -- passed through verbatim,
    # not mapped to `None`, exercising the non-sentinel path on the BEFORE side.
    result = evaluate_candidate(candidate, active_value="already active", score_fn=score_fn)

    assert result.accept is False
    assert result.regressed is True


def test_evaluate_candidate_rejects_when_review_survival_rises_but_citation_span_falls() -> None:
    """The core guard scenario from the spec: a candidate that RAISES the
    review-survival rate (more findings pass Model B) but LOWERS the
    citation-span rate (one of its citations stops verifying) must still be
    REJECTED -- an improvement on the primary axis never buys tolerance for
    a regression on the guard axis."""

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        if instruction == "candidate":
            findings = [
                _finding("c1", [CitationVerdict.VERIFIED_SPAN], _SUPPORTED),  # survives
                _finding(
                    "c2", [CitationVerdict.REJECT], _SUPPORTED
                ),  # citation fails -> no survive
            ]
        else:
            findings = [
                _finding("c1", [CitationVerdict.VERIFIED_SPAN], _OVERSTATED_REJECTED),
                _finding("c2", [CitationVerdict.VERIFIED_SPAN], _OVERSTATED_REJECTED),
            ]
        return _fabricate_result(patient_id, findings)

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)

    before = score_fn("baseline")
    after = score_fn("candidate")

    # Sanity: primary axis genuinely rose (0/2 -> 1/2 survive)...
    assert after.set_d_blocked > before.set_d_blocked
    # ...while the guard genuinely fell (2/2 -> 1/2 verified-span).
    assert after.set_m_caught < before.set_m_caught

    candidate = Candidate(target=ImproveTarget.MODEL_A_PROMPT, new_value="candidate", rationale="r")
    result = evaluate_candidate(candidate, active_value="baseline", score_fn=score_fn)

    assert result.accept is False
    assert result.regressed is True


# --------------------------------------------------------------------------
# End-to-end: run_improvement_cycle with a fake LLM-style proposer and the
# live-style score fn -- an improving candidate promotes, a regressing one
# leaves the active value unchanged.
# --------------------------------------------------------------------------


def _presentation(patient_id: str, claim_ids: list[str]) -> dict[str, object]:
    return {
        "patientId": patient_id,
        "findings": [
            {
                "claimId": claim_id,
                "claimType": "PATIENT_FACT",
                "verdict": "VERIFIED",
                "revisionAttempts": 0,
                "externalEvidence": [],
            }
            for claim_id in claim_ids
        ],
    }


def test_cycle_with_a_live_style_score_fn_promotes_an_improving_candidate(tmp_path: Path) -> None:
    ledger = FilePromotionLedger(tmp_path)

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="better prompt", rationale="proposed")

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        model_b = _SUPPORTED if instruction == "better prompt" else _OVERSTATED_REJECTED
        finding = _finding("c1", [CitationVerdict.VERIFIED_SPAN], model_b)
        return _fabricate_result(patient_id, [finding])

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is True
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "better prompt"


def test_cycle_with_a_live_style_score_fn_rejects_a_regressing_candidate(tmp_path: Path) -> None:
    ledger = FilePromotionLedger(tmp_path)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "already active", version="v0", rationale="seed", now=_NOW
    )

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="worse prompt", rationale="proposed")

    def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
        verdicts = (
            [CitationVerdict.VERIFIED_SPAN, CitationVerdict.REJECT]
            if instruction == "worse prompt"
            else [CitationVerdict.VERIFIED_SPAN, CitationVerdict.VERIFIED_SPAN]
        )
        finding = _finding("c1", verdicts, None)
        return _fabricate_result(patient_id, [finding])

    score_fn = build_live_pipeline_score_fn(benchmark=("patient-a",), run_pipeline=run_pipeline)

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is False
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "already active"
