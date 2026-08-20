"""§45A atomic finalization: write artifacts, then commit the terminal marker.

The load-bearing guarantee: a patient run must never be observable as COMPLETED
(or any other terminal status) while its claims/evidence artifacts are only
partially persisted. `finalize_patient_result` enforces this with a two-phase
sequence --

  1. PREPARE: upsert a summary at `commit_status=PREPARING`, `status=RUNNING`
     (deliberately non-terminal).
  2. WRITE: write claims then evidence to their subcollections (chunked), updating
     the summary's committed counts after each. If the repository raises
     mid-write (a real crash, or `FaultInjected` in tests), that exception
     propagates -- the summary is left at PREPARING/RUNNING, so
     `app.gate.patient_state.derive_patient_status` can never derive COMPLETED
     from it (COMPLETED requires `commit_status == COMMITTED`, spec §43.1).
  3. COMMIT: only once `claims_committed == claims_expected` and
     `evidence_committed == evidence_expected` does the summary flip to
     `commit_status=COMMITTED`, `status=terminal_status`, `stage=PERSISTED`.
     Otherwise `CommitIncompleteError` is raised and the COMMITTED marker is
     never written.

This mirrors the classic two-phase-commit shape but the "phases" are just ordered
writes to one small summary doc plus the artifact subcollections -- Firestore has
no cross-document transaction primitive we need here beyond that ordering, since
the summary doc alone is what `derive_patient_status` and any status-polling API
consult.
"""

from __future__ import annotations

from typing import Any

from app.gate.models import CommitStatus, PatientStage, PatientStatus
from app.storage.errors import CommitIncompleteError
from app.storage.models import (
    PatientSummary,
    claims_collection_path,
    evidence_collection_path,
)
from app.storage.repository import RunRepository

__all__ = ["finalize_patient_result", "is_result_complete", "reconcile"]


def finalize_patient_result(
    repo: RunRepository,
    *,
    run_id: str,
    patient_id: str,
    evidence_snapshot_id: str,
    stage: PatientStage,
    claims: list[tuple[str, dict[str, Any]]],
    evidence: list[tuple[str, dict[str, Any]]],
    terminal_status: PatientStatus,
) -> PatientSummary:
    """Atomically persist one patient's claims/evidence and flip the summary to
    terminal, per spec §45A. See module docstring for the phase sequence.

    Raises whatever `repo.write_documents` raises (e.g. `FaultInjected` in
    tests) if a crash happens mid-write -- the summary is left at PREPARING and
    is never advanced to COMMITTED. Raises `CommitIncompleteError` if, despite
    all writes succeeding, the committed counts don't match the expected counts
    (defensive -- should not happen if `write_documents` is honest about what it
    wrote).
    """
    # Phase 1: PREPARE -- summary is upserted at a non-terminal status/commit_status
    # BEFORE any artifact write, so a crash before this point simply leaves no
    # summary at all (also safely non-terminal).
    summary = PatientSummary(
        run_id=run_id,
        patient_id=patient_id,
        status=PatientStatus.RUNNING,
        stage=stage,
        commit_status=CommitStatus.PREPARING,
        commit_version=1,
        claims_expected=len(claims),
        evidence_expected=len(evidence),
        claims_committed=0,
        evidence_committed=0,
        evidence_snapshot_id=evidence_snapshot_id,
    )
    repo.upsert_patient_summary(summary)

    # Phase 2: WRITE -- artifacts first, terminal marker last. Any exception here
    # (including FaultInjected) propagates with the summary still PREPARING/RUNNING.
    claims_batches = repo.write_documents(claims_collection_path(run_id, patient_id), claims)
    claims_committed = sum(claims_batches)
    summary = summary.model_copy(update={"claims_committed": claims_committed})
    repo.upsert_patient_summary(summary)

    evidence_batches = repo.write_documents(evidence_collection_path(run_id, patient_id), evidence)
    evidence_committed = sum(evidence_batches)
    summary = summary.model_copy(update={"evidence_committed": evidence_committed})
    repo.upsert_patient_summary(summary)

    # Phase 3: COMMIT -- only once every expected artifact is actually committed.
    if claims_committed != summary.claims_expected or evidence_committed != (
        summary.evidence_expected
    ):
        raise CommitIncompleteError(
            f"run={run_id} patient={patient_id}: expected "
            f"{summary.claims_expected} claims / {summary.evidence_expected} evidence, "
            f"committed {claims_committed} claims / {evidence_committed} evidence"
        )

    final_summary = summary.model_copy(
        update={
            "commit_status": CommitStatus.COMMITTED,
            "status": terminal_status,
            "stage": PatientStage.PERSISTED,
            "commit_version": summary.commit_version + 1,
        }
    )
    repo.upsert_patient_summary(final_summary)
    return final_summary


def is_result_complete(summary: PatientSummary) -> bool:
    """True iff `summary` represents a fully, atomically committed result."""
    return (
        summary.commit_status == CommitStatus.COMMITTED
        and summary.claims_committed == summary.claims_expected
        and summary.evidence_committed == summary.evidence_expected
    )


def reconcile(repo: RunRepository, run_id: str, patient_id: str) -> PatientSummary | None:
    """Read back the summary for `(run_id, patient_id)` and flag an interrupted
    finalize for redo -- never fabricates a COMMITTED result.

    Returns `None` if no summary exists yet. If `commit_status == PREPARING`, the
    prior finalize was interrupted (crashed between PREPARE and COMMIT); the
    caller is expected to re-run `finalize_patient_result` for this patient. This
    function only reads and reports -- it never itself advances commit_status.
    """
    summary = repo.get_patient_summary(run_id, patient_id)
    if summary is None:
        return None
    # commit_status == PREPARING here means: needs redo. Returned as-is (still
    # PREPARING) so callers can distinguish "needs redo" from "done" via
    # `is_result_complete`/`commit_status` themselves, rather than this function
    # inventing a new status value.
    return summary
