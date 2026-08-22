"""The real, LIVE `ScoreFn` factory: scores a candidate Model-A prompt by
actually running it through the pipeline against a small benchmark of
patients and measuring the **review-survival rate** -- how many of its
cited findings pass BOTH the deterministic citation gate AND the blinded
Model B (spec §53, Phase C) -- replaces the previous hermetic default
(`app.improve.evaluator.build_benchmark_score_fn`) whose whole documented
point is that it CANNOT vary with the candidate value.

Why review-survival, not the citation verified-span rate: a live round
showed Model A's citation quoting is already saturated at 100% on this
cohort (no gradient to optimise), while only ~59% of cited findings fully
survived Model B (the rest OVERSTATED / WRONG_POPULATION / INSUFFICIENT_
EVIDENCE). The headroom -- and the exact weakness the README already owns
(Model B over-aggressive) -- is in finding QUALITY, so that is the primary
objective; the citation verified-span rate is kept as a no-regression GUARD.

`build_live_pipeline_score_fn` is deliberately split from `run_patient`
itself: `run_pipeline` is injected, so this module contains no Gemini/
Firestore/FHIR construction of its own and stays trivially hermetic-testable
with a fake -- only `app.api.composition.get_improve_score_fn` wires a REAL
`run_pipeline` (closing over the live Gemini clients + `run_patient`), and
that composition is the only LIVE, token-costing seam. Never call the
returned `ScoreFn` from `make check`'s hermetic suite.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.citation.models import CitationVerdict
from app.improve.evaluator import ScoreFn, clinician_agreement_from_holdout
from app.improve.models import Dataset, Metrics
from app.pipeline.models import FindingResult, PatientRunResult
from app.review.models import ReviewFinding

__all__ = ["RunPipeline", "build_live_pipeline_score_fn"]

#: Runs ONE benchmark patient through the pipeline with a given candidate
#: Model-A system-instruction override (`None` = use `run_patient`'s pinned
#: default, `app.agent.prompts.MODEL_A_SYSTEM_INSTRUCTION`) and returns its
#: `PatientRunResult`. Injectable so tests drive `build_live_pipeline_
#: score_fn` with a hermetic fake that fabricates `PatientRunResult`s
#: instead of ever calling `app.pipeline.runner.run_patient` for real. The
#: first argument is whichever patient identifier `benchmark` used to name
#: that patient (e.g. one of `app.api.composition.DEMO_PATIENT_IDS`) --
#: resolving it to an actual FHIR bundle/evidence snapshot/Gemini client is
#: entirely the injected callable's own business, not this module's.
RunPipeline = Callable[[str, str | None], PatientRunResult]

#: Scale factor used to express a (fractional) rate as an integer "basis
#: points" count so it fits `Metrics`' `int` axes as a genuine RATE rather
#: than a raw count -- a raw count would be gameable (fewer claims emitted
#: -> fewer rejects, with no real quality improvement); a normalized rate is
#: not.
_RATE_SCALE = 10_000


def _effective_instruction(candidate_prompt: str) -> str | None:
    """Map the `ScoreFn` sentinel for "no promotion exists yet" to
    `run_patient`'s own "use the pinned default" sentinel.

    `app.improve.cycle.run_improvement_cycle` calls `score_fn(active_value)`
    where `active_value = ledger.active_value(target) or ""` -- an empty
    string means "nothing has ever been promoted", exactly the case
    `app.improve.registry.resolve_artifact` maps to its `default` argument.
    Mapping `""` to `None` here keeps that same contract: scoring the
    not-yet-promoted baseline actually runs the REAL current Model-A prompt,
    not a literal empty system instruction (which would trivially, and
    misleadingly, score as terrible). A genuine non-empty candidate/
    promoted value is passed through verbatim.
    """
    return candidate_prompt or None


def _survives_review(finding: FindingResult) -> bool:
    """Whether a single CITED finding survives the full review: every one of
    its citations verified (`VERIFIED_SPAN`) AND the blinded Model B returned
    `SUPPORTED` without asking for rejection.

    `model_b_verdict is None` means the deterministic layer BLOCKED the claim
    before Model B ever ran (a citation `REJECT`), so it did not survive.
    Only ever called on a finding that already has >=1 external citation.
    """
    if not all(c.verdict == CitationVerdict.VERIFIED_SPAN for c in finding.citation_results):
        return False
    verdict = finding.model_b_verdict
    return (
        verdict is not None
        and verdict.finding == ReviewFinding.SUPPORTED
        and not verdict.should_reject
    )


def _review_survival_counts(result: PatientRunResult) -> tuple[int, int]:
    """Return `(survived, cited)` finding counts for one patient's run. A
    finding is "cited" iff it carries >=1 external-evidence citation
    (`citation_results`); of those, "survived" iff `_survives_review`. A
    finding with no external citations (a patient-fact restatement, an
    uncertainty admission, ...) is excluded from BOTH counts -- there is no
    external claim to survive. A run with zero cited findings contributes
    `(0, 0)`, never raises.
    """
    survived = 0
    cited = 0
    for finding in result.findings:
        if not finding.citation_results:
            continue
        cited += 1
        if _survives_review(finding):
            survived += 1
    return survived, cited


def _verified_span_counts(result: PatientRunResult) -> tuple[int, int]:
    """Return `(verified, total)` external-evidence citation counts for one
    patient's run -- the GUARD axis. `total` is every `CitationResult`
    produced across every FINAL finding; `verified` is the subset whose
    `verdict == CitationVerdict.VERIFIED_SPAN`. A run with zero citations
    contributes `(0, 0)`, never raises.
    """
    total = 0
    verified = 0
    for finding in result.findings:
        for citation in finding.citation_results:
            total += 1
            if citation.verdict == CitationVerdict.VERIFIED_SPAN:
                verified += 1
    return verified, total


def build_live_pipeline_score_fn(
    *,
    benchmark: Sequence[str],
    run_pipeline: RunPipeline,
    dataset_holdout: Dataset | None = None,
) -> ScoreFn:
    """Build a LIVE `ScoreFn`: scoring a candidate prompt actually runs
    `run_pipeline` once per patient id in `benchmark` with that prompt (via
    `run_patient`'s `model_a_system_instruction` override) and measures two
    pooled rates across ALL of them.

    PRIMARY objective -- the **review-survival rate**: of all cited findings
    (findings carrying >=1 external citation), the fraction that both verify
    deterministically AND are `SUPPORTED` by the blinded Model B (see
    `_survives_review`). This is the axis with real headroom (baseline ~59%).

    GUARD -- the **citation verified-span rate**: the fraction of external
    citations whose `verdict == VERIFIED_SPAN`. Already saturated at 100% on
    the current cohort; kept only so a candidate that improves review-
    survival by DROPPING citation quality is rejected as a regression.

    Both are encoded as integer "basis points" (0..10000, `_RATE_SCALE`)
    across `Metrics`' axes so they behave correctly under `app.improve.
    evaluator.compare_metrics`'s ordering:
      - `set_d_blocked` = round(review_survival_rate * 10000) -- HIGHER is
        better; the PRIMARY objective.
      - `false_reject` = 10000 - `set_d_blocked` -- LOWER is better; derived
        from the SAME review-survival rate so the two can never disagree.
      - `set_m_caught` = round(citation_span_rate * 10000) -- HIGHER is
        better; the GUARD. A candidate that lowers citation quality lowers
        this axis, which `compare_metrics` reads as a regression that blocks
        acceptance even if the primary axis rose.
      - `clinician_agreement` = `clinician_agreement_from_holdout(
        dataset_holdout)` when a holdout `Dataset` is given, else a neutral
        `1.0`. It is the same for the before/after side (labels attach to the
        already-run baseline, not a candidate's fresh output), so it is
        informational and never on its own flips accept/reject.

    A pooled rate with an empty denominator (no cited findings, or no
    citations at all) scores `1.0` -- "no data -> no penalty", matching
    `clinician_agreement_from_holdout`'s own empty-set convention.

    LIVE: the returned function calls `run_pipeline` -- a real, token-costing
    Model-A call in production (`app.api.composition.get_improve_score_fn`).
    Never call it from `make check`'s hermetic suite; tests pass a fake
    `run_pipeline` that fabricates `PatientRunResult`s instead.
    """
    agreement = (
        clinician_agreement_from_holdout(dataset_holdout) if dataset_holdout is not None else 1.0
    )

    def score(candidate_prompt: str) -> Metrics:
        instruction = _effective_instruction(candidate_prompt)
        survived_total = 0
        cited_total = 0
        verified_total = 0
        citation_total = 0
        for patient_id in benchmark:
            result = run_pipeline(patient_id, instruction)
            survived, cited = _review_survival_counts(result)
            verified, citations = _verified_span_counts(result)
            survived_total += survived
            cited_total += cited
            verified_total += verified
            citation_total += citations
        review_rate = (survived_total / cited_total) if cited_total else 1.0
        citation_rate = (verified_total / citation_total) if citation_total else 1.0
        review_scaled = round(review_rate * _RATE_SCALE)
        return Metrics(
            set_d_blocked=review_scaled,
            set_m_caught=round(citation_rate * _RATE_SCALE),
            false_reject=_RATE_SCALE - review_scaled,
            clinician_agreement=agreement,
        )

    return score
