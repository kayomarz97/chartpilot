"""Result models for the Phase 14 end-to-end pipeline.

`PatientRunResult` is what `app.pipeline.runner.run_patient` returns: the
full outcome of chaining FHIR fetch through normalization, rule evaluation,
evidence retrieval, AI reasoning, citation checking, independent review,
final gating, and persistence for ONE patient. A `FindingResult` bundles one
claim with everything decided about it (its final `ClaimVerdict`, the
citation results for its external evidence, and Model B's verdict, if one
was run).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.agent.models import Claim
from app.citation.models import CitationResult
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.normalize.adr import NormalizedAdverseReaction
from app.normalize.medication import NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation
from app.review.models import ModelBVerdict
from app.rules.models import RuleResult
from app.validation.models import ValidityResult

__all__ = ["FindingResult", "PatientRunSummary", "PatientRunResult"]


class FindingResult(BaseModel):
    """One claim plus its full downstream disposition.

    `claim` and `citation_results` reflect the FINAL claim after the bounded
    "gate-failure -> revise -> retry" loop (spec §53, Phase A;
    `app.pipeline.runner.run_patient`'s `max_revise_iterations`), not
    necessarily what Model A emitted on its first pass. `revision_attempts`
    is a defaulted trace field (0 for every finding that never entered the
    loop, including every construction site that predates it) counting how
    many times that loop successfully swapped in a re-quoted claim -- it is
    informational only and never affects `verdict`, which is decided solely
    by `app.gate.claim_gate.finalize_claim_verdict` against whatever claim
    ended up final.
    """

    model_config = ConfigDict(frozen=True)

    claim: Claim
    verdict: ClaimVerdict
    citation_results: tuple[CitationResult, ...]
    model_b_verdict: ModelBVerdict | None
    revision_attempts: int = 0


class PatientRunSummary(BaseModel):
    """The terminal run-state for one patient (spec §43)."""

    model_config = ConfigDict(frozen=True)

    status: PatientStatus
    stage: PatientStage
    commit_status: CommitStatus


class PatientRunResult(BaseModel):
    """The full outcome of running one patient through the pipeline.

    `error` is `None` on any non-FAILED outcome (including a legitimately
    empty-findings COMPLETED run) and is always set alongside
    `summary.status == PatientStatus.FAILED` -- a failure is never silent
    (spec: "a FHIR/normalize error -> the run ends FAILED, never silently
    'no findings'").

    `patient_name`/`normalized_observations`/`normalized_medications`/
    `normalized_adverse_reactions` (TD-011) are ADDITIVE, defaulted fields:
    `run_patient` already computes all of these locally, so populating them
    costs nothing new, and every existing caller/test that constructs a
    `PatientRunResult` without them (or calls `run_patient` and only reads
    the pre-existing fields) is byte-for-byte unaffected. They exist so
    `app.api.presentation.build_presentation` can build the UI-shaped
    payload without re-deriving normalized facts from raw FHIR a second
    time. Left at their defaults (empty) on a FAILED run, matching
    `findings`/`rule_results`/etc.
    """

    model_config = ConfigDict(frozen=True)

    patient_id: str
    summary: PatientRunSummary
    findings: tuple[FindingResult, ...]
    rule_results: tuple[RuleResult, ...]
    validity_results: tuple[ValidityResult, ...]
    timeline_events: tuple[str, ...]
    error: str | None = None
    patient_name: str = ""
    normalized_observations: tuple[NormalizedObservation, ...] = ()
    normalized_medications: tuple[NormalizedMedicationOrder, ...] = ()
    normalized_adverse_reactions: tuple[NormalizedAdverseReaction, ...] = ()
