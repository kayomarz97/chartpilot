"""Enums for the final safety gate: claim verdicts (spec §42) and the
patient run-state machine (spec §43).

`STAGE_ORDER` fixes the canonical, monotonically-increasing pipeline stage
sequence a patient run passes through (§43.2); `stage_index` in
`app.gate.patient_state` looks positions up in it to enforce that a run can
never silently rewind to an earlier stage.

`NON_TERMINAL_STATUSES` / `TERMINAL_STATUSES` partition `PatientStatus`:
QUEUED and RUNNING are the only statuses a run can still leave on its own;
every other status is a stopping point (successful or not) that nothing
downstream should keep polling past.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ClaimVerdict",
    "PatientStatus",
    "PatientStage",
    "STAGE_ORDER",
    "CommitStatus",
    "NON_TERMINAL_STATUSES",
    "TERMINAL_STATUSES",
    "is_terminal",
]


class ClaimVerdict(StrEnum):
    """The final, post-gate outcome for one claim (spec §42)."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    CONFLICTING = "conflicting"
    UNVERIFIABLE = "unverifiable"
    REJECTED = "rejected"
    REQUIRES_REVIEW = "requires_review"


class PatientStatus(StrEnum):
    """The overall status of one patient's processing run (spec §43.1)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    DEAD_LETTER = "dead_letter"


class PatientStage(StrEnum):
    """One step of the pipeline a patient run passes through (spec §43.2).

    Members are declared in pipeline order; `STAGE_ORDER` below is the
    canonical sequence other code should iterate/index against rather than
    relying on declaration order of the enum itself.
    """

    QUEUED = "queued"
    FETCHING = "fetching"
    NORMALIZING = "normalizing"
    RULES_EVALUATED = "rules_evaluated"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    AI_REASONING = "ai_reasoning"
    CITATION_CHECK = "citation_check"
    INDEPENDENT_REVIEW = "independent_review"
    FINAL_VALIDATION = "final_validation"
    PERSISTED = "persisted"


#: Canonical, ordered pipeline-stage sequence (spec §43.2).
STAGE_ORDER: tuple[PatientStage, ...] = (
    PatientStage.QUEUED,
    PatientStage.FETCHING,
    PatientStage.NORMALIZING,
    PatientStage.RULES_EVALUATED,
    PatientStage.EVIDENCE_RETRIEVAL,
    PatientStage.AI_REASONING,
    PatientStage.CITATION_CHECK,
    PatientStage.INDEPENDENT_REVIEW,
    PatientStage.FINAL_VALIDATION,
    PatientStage.PERSISTED,
)


class CommitStatus(StrEnum):
    """The state of persisting a patient run's results (spec §45A)."""

    PREPARING = "preparing"
    COMMITTED = "committed"
    PARTIAL = "partial"
    FAILED = "failed"


#: The only statuses a run can still leave on its own.
NON_TERMINAL_STATUSES: frozenset[PatientStatus] = frozenset(
    {PatientStatus.QUEUED, PatientStatus.RUNNING}
)

#: Every status that is a stopping point (successful or not).
TERMINAL_STATUSES: frozenset[PatientStatus] = frozenset(
    status for status in PatientStatus if status not in NON_TERMINAL_STATUSES
)


def is_terminal(status: PatientStatus) -> bool:
    """True iff `status` is a stopping point (i.e. not QUEUED/RUNNING)."""
    return status in TERMINAL_STATUSES
