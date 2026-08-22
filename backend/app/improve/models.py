"""Data shapes for the outer self-improving loop (Phase C).

Everything here is a pure data model -- no I/O, no clock, no RNG. The tier
boundary this package enforces lives here first: `ImproveTarget` enumerates
ONLY the AUTO-tunable targets (spec: Model-A prompt wording, evidence-
retrieval ranking); `FROZEN_TARGET_NAMES` documents known FROZEN-tier
identifiers this package must never be able to touch (clinical rules, the
validity math, the final gate, normalization) purely for clearer error
messages -- the actual enforcement is default-deny in
`app.improve.proposer.assert_target_allowed`, which refuses ANY string that
is not a value of `ImproveTarget`, whether or not it happens to appear in
this frozenset. A brand-new FROZEN component added elsewhere in the
codebase is therefore refused automatically, without this list ever needing
to be updated to know about it.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "ImproveTarget",
    "FROZEN_TARGET_NAMES",
    "TrainingCase",
    "case_is_automated_flag",
    "Dataset",
    "Candidate",
    "Metrics",
    "EvaluationResult",
    "PromotionRecord",
    "ImprovementReport",
]


class ImproveTarget(StrEnum):
    """The ONLY components the outer loop may ever propose changing (spec:
    AUTO tier). Adding a member here is a deliberate, reviewed decision to
    widen what the loop can touch -- never do it casually."""

    MODEL_A_PROMPT = "model_a_prompt"
    EVIDENCE_RANKING = "evidence_ranking"


#: Known FROZEN-tier identifiers (clinical rules, validity math, the final
#: gate, normalization) -- documentation only, used to give
#: `assert_target_allowed` a clearer error message. NOT the enforcement
#: mechanism itself: `assert_target_allowed` is default-deny against the
#: `ImproveTarget` allowlist, so an identifier missing from this frozenset is
#: refused exactly the same as one present in it.
FROZEN_TARGET_NAMES: frozenset[str] = frozenset(
    {
        "k_high_risk_001",
        "clinical_rules",
        "rules_engine",
        "egfr_ckd_epi_2021_cr",
        "corrected_calcium",
        "anion_gap",
        "validity_metrics",
        "validity_engine",
        "finalize_claim_verdict",
        "final_gate",
        "citation_gates",
        "normalize_observation",
        "normalize_quantity",
        "normalization",
    }
)


class TrainingCase(BaseModel):
    """One claim's joined automated signals + (if any) clinician label --
    the outer loop's unit of training/evaluation data (spec §53).

    `verdict`/`citation_verdicts` are the exact-cased strings as persisted on
    the presentation payload (`app.api.presentation.build_presentation`,
    e.g. `"REJECTED"`, `"REJECT"`) -- callers comparing them should normalize
    case themselves (see `case_is_automated_flag`) rather than assume one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_id: str
    claim_id: str
    claim_type: str
    verdict: str
    citation_verdicts: tuple[str, ...]
    model_b_should_reject: bool
    revision_attempts: int
    clinician_action: str | None = None
    clinician_note: str = ""


#: Automated verdicts that count as "the automated layer flagged this claim".
_GATE_FAILURE_VERDICTS = frozenset({"rejected", "requires_review"})
#: Citation verdicts that count as "the citation layer flagged this claim".
_GATE_FAILURE_CITATION_VERDICTS = frozenset({"reject", "flag_for_review"})
#: Clinician actions that count as "the clinician flagged this claim".
_CLINICIAN_FLAG_ACTIONS = frozenset({"override", "correct"})


def case_is_automated_flag(case: TrainingCase) -> bool:
    """True iff the AUTOMATED layer (a citation gate, or Model B) flagged
    this case -- independent of whether a clinician ever looked at it.
    Case-insensitive over `verdict`/`citation_verdicts` since those are
    persisted uppercase but this package should not depend on that."""
    return (
        case.verdict.lower() in _GATE_FAILURE_VERDICTS
        or case.model_b_should_reject
        or any(v.lower() in _GATE_FAILURE_CITATION_VERDICTS for v in case.citation_verdicts)
    )


def _case_is_clinician_flag(case: TrainingCase) -> bool:
    """True iff a clinician recorded an OVERRIDE/CORRECT label on this case
    (a CONFIRM, or no label at all, is not a flag)."""
    return case.clinician_action is not None and case.clinician_action.lower() in (
        _CLINICIAN_FLAG_ACTIONS
    )


#: Deterministic train/holdout split ratio: 1 in `_HOLDOUT_MODULUS` claim ids
#: (by a stable hash) go to holdout, the rest to train -- roughly an 80/20
#: split with no randomness involved anywhere.
_HOLDOUT_MODULUS = 5
_HOLDOUT_BUCKET = 0


def _in_holdout(claim_id: str) -> bool:
    """A pure, stable function of `claim_id` alone -- same input always
    yields the same train/holdout assignment, across processes and runs (no
    RNG, no wall clock: reproducibility is the entire point of splitting
    this way rather than shuffling). Uses the first byte of a SHA-256 digest
    so the split is not correlated with any lexical property of claim ids
    (e.g. a shared prefix)."""
    digest = hashlib.sha256(claim_id.encode("utf-8")).digest()
    return (digest[0] % _HOLDOUT_MODULUS) == _HOLDOUT_BUCKET


class Dataset(BaseModel):
    """A collection of `TrainingCase`s, with the deterministic train/holdout
    split the outer loop's "no training on the held-out eval" rule depends
    on (README: avoids the Model-B "game your own number" trap -- a
    candidate must never be scored on the same cases it (or a human
    reviewing it) could have seen while drafting it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: tuple[TrainingCase, ...]

    @property
    def failure_museum(self) -> tuple[TrainingCase, ...]:
        """Cases that failed a gate (a citation REJECT/FLAG_FOR_REVIEW, an
        automated verdict of REJECTED/REQUIRES_REVIEW, or a Model-B
        should-reject) OR were labeled OVERRIDE/CORRECT by a clinician --
        the concrete, inspectable evidence a proposer reasons from."""
        return tuple(
            case
            for case in self.cases
            if case_is_automated_flag(case) or _case_is_clinician_flag(case)
        )

    def split(self) -> tuple[Dataset, Dataset]:
        """Deterministically partition `cases` into `(train, holdout)` by a
        stable hash of `claim_id` (see `_in_holdout`) -- same `Dataset` ->
        same split, always, and the two halves are disjoint by construction
        (every case goes to exactly one side)."""
        train: list[TrainingCase] = []
        holdout: list[TrainingCase] = []
        for case in self.cases:
            (holdout if _in_holdout(case.claim_id) else train).append(case)
        return Dataset(cases=tuple(train)), Dataset(cases=tuple(holdout))


class Candidate(BaseModel):
    """One proposed change to exactly one AUTO-tier target (spec: never a
    diff, never a partial edit -- a full replacement VALUE for `target`,
    e.g. an entire candidate prompt string)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: ImproveTarget
    new_value: str
    rationale: str


class Metrics(BaseModel):
    """The benchmark score components `evaluate_candidate` compares before
    vs. after a candidate (spec §22 corruption suite + clinician agreement).
    See `app.improve.evaluator.compare_metrics` for the exact "better/worse"
    ordering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    set_d_blocked: int
    set_m_caught: int
    false_reject: int
    clinician_agreement: float


class EvaluationResult(BaseModel):
    """The outcome of scoring one `Candidate` against the active artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: bool
    improved: bool
    regressed: bool
    metrics_before: Metrics
    metrics_after: Metrics
    detail: str


class PromotionRecord(BaseModel):
    """One entry in the append-only promotion ledger (`app.improve.promote.
    PromotionLedger`) -- either a fresh promotion or a rollback re-surfacing
    a prior version as active again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: ImproveTarget
    version: str
    active: bool
    rationale: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _reject_naive(cls, v: datetime) -> datetime:
        """Fail closed: no naive datetime may ever exist in this model."""
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("PromotionRecord.created_at must be tz-aware; got naive")
        return v.astimezone(UTC)


class ImprovementReport(BaseModel):
    """The full outcome of one `app.improve.cycle.run_improvement_cycle`
    call -- always returned, never raised (fail-closed: an error inside the
    cycle becomes `accepted=False` plus a `detail` explaining why, not an
    exception escaping to the caller)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: ImproveTarget
    accepted: bool
    evaluation: EvaluationResult | None
    promotion: PromotionRecord | None
    detail: str
