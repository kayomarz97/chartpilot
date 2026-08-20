"""Patient run-state machine (spec §43).

`derive_patient_status` folds the set of per-claim `ClaimVerdict`s plus
pipeline bookkeeping (current stage, commit status, and any explicit
terminal-error flags) into one `PatientStatus` for the whole run.
`assert_state_invariants` then checks a constructed `PatientRunState` is
internally consistent (spec §43.3) -- e.g. a run can never claim COMPLETED
without actually having reached PERSISTED and COMMITTED.

Pure functions, no I/O, no LLM calls.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.gate.errors import StateInvariantError
from app.gate.models import STAGE_ORDER, ClaimVerdict, CommitStatus, PatientStage, PatientStatus

__all__ = [
    "PatientRunState",
    "stage_index",
    "can_advance_stage",
    "derive_patient_status",
    "assert_state_invariants",
]


class PatientRunState(BaseModel):
    """The full run-state of one patient's processing pipeline (spec §43)."""

    model_config = ConfigDict(frozen=True)

    status: PatientStatus
    stage: PatientStage
    commit_status: CommitStatus


def stage_index(stage: PatientStage) -> int:
    """The position of `stage` in the canonical `STAGE_ORDER` sequence."""
    return STAGE_ORDER.index(stage)


def can_advance_stage(current: PatientStage, target: PatientStage) -> bool:
    """True iff moving from `current` to `target` does not rewind the stage
    (spec §43.2: a patient run's stage is monotonically non-decreasing).
    """
    return stage_index(target) >= stage_index(current)


#: Claim verdicts that force the whole run into human review.
_REVIEW_TRIGGERING_VERDICTS = frozenset({ClaimVerdict.REQUIRES_REVIEW, ClaimVerdict.CONFLICTING})

#: Claim verdicts that, mixed with at least one VERIFIED, mean the run
#: persisted successfully but did not fully verify every claim.
_PARTIAL_VERDICTS = frozenset(
    {ClaimVerdict.PARTIALLY_VERIFIED, ClaimVerdict.REJECTED, ClaimVerdict.UNVERIFIABLE}
)


def derive_patient_status(
    claim_verdicts: Sequence[ClaimVerdict],
    *,
    stage: PatientStage,
    commit_status: CommitStatus,
    failed: bool = False,
    timed_out: bool = False,
    dead_letter: bool = False,
) -> PatientStatus:
    """Derive the overall `PatientStatus` for one patient run (spec §43.1).

    Order of evaluation:
      1. Explicit terminal errors (`failed`/`timed_out`/`dead_letter`) win
         outright -- these are reported by the orchestrator, not inferred,
         and always take precedence over anything claim-verdict-shaped.
      2. Any claim needing a human (REQUIRES_REVIEW or CONFLICTING) ->
         FLAGGED_FOR_REVIEW, even if the run has otherwise persisted.
      3. COMPLETED requires ALL of: stage == PERSISTED, commit_status ==
         COMMITTED, and every claim verdict == VERIFIED. An empty
         `claim_verdicts` with PERSISTED+COMMITTED is COMPLETED too -- a
         zero-finding but fully-processed run is a legitimate, successful
         outcome, not a failure to process.
      4. Otherwise, if the run HAS persisted+committed but the verdict mix
         includes at least one non-VERIFIED, non-review-triggering verdict
         (PARTIALLY_VERIFIED / REJECTED / UNVERIFIABLE) -> PARTIAL.
      5. Otherwise the run has not yet reached PERSISTED+COMMITTED and has
         no terminal error or review trigger -> RUNNING (still in
         progress).
    """
    if failed:
        return PatientStatus.FAILED
    if timed_out:
        return PatientStatus.TIMED_OUT
    if dead_letter:
        return PatientStatus.DEAD_LETTER

    if any(verdict in _REVIEW_TRIGGERING_VERDICTS for verdict in claim_verdicts):
        return PatientStatus.FLAGGED_FOR_REVIEW

    persisted_and_committed = stage == PatientStage.PERSISTED and commit_status == (
        CommitStatus.COMMITTED
    )

    if persisted_and_committed:
        if all(verdict == ClaimVerdict.VERIFIED for verdict in claim_verdicts):
            return PatientStatus.COMPLETED
        if any(verdict in _PARTIAL_VERDICTS for verdict in claim_verdicts):
            return PatientStatus.PARTIAL

    return PatientStatus.RUNNING


def assert_state_invariants(state: PatientRunState) -> None:
    """Raise `StateInvariantError` if `state` violates a §43.3 invariant.

    Checks kept minimal but real:
      - COMPLETED requires stage == PERSISTED AND commit_status ==
        COMMITTED (the load-bearing invariant: a run must never report
        itself fully done while its results are still mid-persist or only
        partially committed).
      - RUNNING requires `stage` to be one of the canonical
        `PatientStage` members (always true for a validated
        `PatientRunState`, asserted here defensively as the state machine's
        contract rather than relying solely on pydantic's enum coercion).
    """
    if state.status == PatientStatus.COMPLETED:
        if state.stage != PatientStage.PERSISTED:
            raise StateInvariantError(
                f"status=COMPLETED requires stage=PERSISTED, got stage={state.stage!r}"
            )
        if state.commit_status != CommitStatus.COMMITTED:
            raise StateInvariantError(
                "status=COMPLETED requires commit_status=COMMITTED, got "
                f"commit_status={state.commit_status!r}"
            )

    if state.status == PatientStatus.RUNNING and state.stage not in STAGE_ORDER:
        raise StateInvariantError(f"status=RUNNING has an invalid stage={state.stage!r}")
