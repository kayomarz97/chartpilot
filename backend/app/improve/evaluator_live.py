"""The real, LIVE `ScoreFn` factory: scores a candidate Model-A prompt by
actually running it through the pipeline against a small benchmark of
patients and measuring how many external-evidence citations verify (spec
§53, Phase C) -- replaces the previous hermetic default
(`app.improve.evaluator.build_benchmark_score_fn`) whose whole documented
point is that it CANNOT vary with the candidate value.

`build_live_pipeline_score_fn` is deliberately split from `run_patient`
itself: `run_pipeline` is injected (spec: "runs ONE benchmark patient
through `run_patient` WITH the candidate prompt"), so this module contains
no Gemini/Firestore/FHIR construction of its own and stays trivially
hermetic-testable with a fake -- only `app.api.composition.
get_improve_score_fn` wires a REAL `run_pipeline` (closing over the live
Gemini clients + `run_patient`), and that composition is the only LIVE,
token-costing seam. Never call the returned `ScoreFn` from `make check`'s
hermetic suite.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.citation.models import CitationVerdict
from app.improve.evaluator import ScoreFn, clinician_agreement_from_holdout
from app.improve.models import Dataset, Metrics
from app.pipeline.models import PatientRunResult

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

#: Scale factor used to express the (fractional) verified-span rate as an
#: integer "basis points" count so it fits `Metrics.set_d_blocked`/
#: `Metrics.false_reject` (both typed `int`) as a genuine RATE rather than a
#: raw citation count -- see `build_live_pipeline_score_fn`'s docstring for
#: why a raw count would be gameable (fewer claims emitted -> fewer
#: rejects, with no real quality improvement) and a normalized rate is not.
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


def _verified_span_counts(result: PatientRunResult) -> tuple[int, int]:
    """Return `(verified, total)` external-evidence citation counts for one
    patient's run. `total` is every `CitationResult` produced across every
    FINAL finding (one per `ExternalEvidenceRef` the claim carries after any
    Phase A revise-loop repair, see `app.pipeline.runner.run_patient`'s
    per-claim citation check) -- `verified` is the subset whose `verdict ==
    CitationVerdict.VERIFIED_SPAN`. A patient run with zero findings/
    citations (including a `FAILED` run) contributes `(0, 0)`, never raises.
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
    `run_patient`'s `model_a_system_instruction` override) and measures the
    fraction of external-evidence citations across ALL of them whose
    `CitationResult.verdict == CitationVerdict.VERIFIED_SPAN` -- the PRIMARY,
    fully deterministic, clinician-free objective this evaluator scores a
    candidate on (spec §53: "more of its verbatim citation spans verify").

    That verified-span RATE is encoded as an integer "basis points" value
    (0..10000, see `_RATE_SCALE`) split across two `Metrics` axes so it
    behaves as a genuine rate, not a gameable raw count, under `app.improve.
    evaluator.compare_metrics`'s ordering:
      - `set_d_blocked` = round(rate * 10000) -- HIGHER is better, i.e. more
        verified citations (per `compare_metrics`'s existing "higher
        better" ordering for this axis).
      - `false_reject` = 10000 - that value -- LOWER is better, i.e. fewer
        REJECT/FLAG_FOR_REVIEW citations (per `compare_metrics`'s existing
        "lower better" ordering for this axis).
    Both numbers are derived from the SAME rate, so they can never disagree
    with each other -- a candidate that improves the rate always improves
    `set_d_blocked` and reduces `false_reject` together, never one without
    the other. A benchmark run producing zero total citations scores the
    rate as `1.0` (no data -> no penalty, matching `app.improve.evaluator.
    clinician_agreement_from_holdout`'s own empty-set convention).

    `set_m_caught` is held at a fixed `0` -- this live evaluator does not
    replay the frozen §22 corruption suite (that stays `app.improve.
    evaluator.build_benchmark_score_fn`'s job); a constant never causes a
    spurious improve/regress signal on its own.

    `clinician_agreement` is `app.improve.evaluator.
    clinician_agreement_from_holdout(dataset_holdout)` when a holdout
    `Dataset` is given, else a neutral constant `1.0` (an axis with nothing
    to measure imposes no penalty, mirroring that same function's own
    empty-holdout convention).

    LIVE: the returned function calls `run_pipeline` -- a real, token-
    costing Model-A call in production (`app.api.composition.
    get_improve_score_fn`). Never call it from `make check`'s hermetic
    suite; tests pass a fake `run_pipeline` that fabricates
    `PatientRunResult`s instead.
    """
    agreement = (
        clinician_agreement_from_holdout(dataset_holdout) if dataset_holdout is not None else 1.0
    )

    def score(candidate_prompt: str) -> Metrics:
        instruction = _effective_instruction(candidate_prompt)
        verified_total = 0
        grand_total = 0
        for patient_id in benchmark:
            result = run_pipeline(patient_id, instruction)
            verified, total = _verified_span_counts(result)
            verified_total += verified
            grand_total += total
        rate = (verified_total / grand_total) if grand_total else 1.0
        verified_scaled = round(rate * _RATE_SCALE)
        return Metrics(
            set_d_blocked=verified_scaled,
            set_m_caught=0,
            false_reject=_RATE_SCALE - verified_scaled,
            clinician_agreement=agreement,
        )

    return score
