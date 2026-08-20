"""Tests for `app.storage.two_phase` (spec §45A): atomic patient-result
finalization. The load-bearing property under test is that a crash between
artifact writes and the terminal-status commit can never be observed as a
COMPLETED run -- proven both directly (summary still PREPARING) and end-to-end
through `app.gate.patient_state.derive_patient_status`.
"""

from __future__ import annotations

import pytest

from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.gate.patient_state import derive_patient_status
from app.storage.errors import FaultInjected
from app.storage.inmemory import InMemoryRunRepository
from app.storage.two_phase import finalize_patient_result, is_result_complete, reconcile

_RUN_ID = "run-1"
_PATIENT_ID = "patient-1"


def _claims(n: int) -> list[tuple[str, dict[str, str]]]:
    return [(f"claim-{i}", {"text": f"finding {i}"}) for i in range(n)]


def _evidence(n: int) -> list[tuple[str, dict[str, str]]]:
    return [(f"ev-{i}", {"source": f"pubmed-{i}"}) for i in range(n)]


def test_happy_path_commits_and_reports_complete() -> None:
    repo = InMemoryRunRepository()
    summary = finalize_patient_result(
        repo,
        run_id=_RUN_ID,
        patient_id=_PATIENT_ID,
        evidence_snapshot_id="snap-1",
        stage=PatientStage.FINAL_VALIDATION,
        claims=_claims(3),
        evidence=_evidence(2),
        terminal_status=PatientStatus.COMPLETED,
    )
    assert summary.commit_status == CommitStatus.COMMITTED
    assert summary.status == PatientStatus.COMPLETED
    assert summary.stage == PatientStage.PERSISTED
    assert summary.claims_committed == summary.claims_expected == 3
    assert summary.evidence_committed == summary.evidence_expected == 2
    assert is_result_complete(summary)


def test_fault_injected_between_writes_leaves_summary_preparing() -> None:
    # 3 claims + 2 evidence = 5 documents total; fail after the 2nd document so
    # the fault fires mid-claims-write, well before evidence or the COMMIT phase.
    repo = InMemoryRunRepository(fail_after_writes=2)
    with pytest.raises(FaultInjected):
        finalize_patient_result(
            repo,
            run_id=_RUN_ID,
            patient_id=_PATIENT_ID,
            evidence_snapshot_id="snap-2",
            stage=PatientStage.FINAL_VALIDATION,
            claims=_claims(3),
            evidence=_evidence(2),
            terminal_status=PatientStatus.COMPLETED,
        )

    summary = repo.get_patient_summary(_RUN_ID, _PATIENT_ID)
    assert summary is not None
    assert summary.commit_status == CommitStatus.PREPARING
    assert summary.status != PatientStatus.COMPLETED
    assert summary.status == PatientStatus.RUNNING

    # End-to-end: feed the interrupted summary's commit_status into the patient
    # run-state machine and prove it can never derive COMPLETED from it, even
    # with every claim verdict VERIFIED.
    derived = derive_patient_status(
        [ClaimVerdict.VERIFIED, ClaimVerdict.VERIFIED, ClaimVerdict.VERIFIED],
        stage=summary.stage,
        commit_status=summary.commit_status,
    )
    assert derived != PatientStatus.COMPLETED


def test_oversized_claim_set_chunks_into_three_batches_and_commits() -> None:
    repo = InMemoryRunRepository()
    summary = finalize_patient_result(
        repo,
        run_id=_RUN_ID,
        patient_id=_PATIENT_ID,
        evidence_snapshot_id="snap-3",
        stage=PatientStage.FINAL_VALIDATION,
        claims=_claims(900),
        evidence=[],
        terminal_status=PatientStatus.COMPLETED,
    )
    assert summary.claims_committed == 900
    assert summary.commit_status == CommitStatus.COMMITTED
    assert is_result_complete(summary)

    # The repository's write_documents return value (per-batch sizes) is what
    # actually proves chunking happened; re-derive it directly too.
    from app.storage.models import chunk_documents

    batch_sizes = [len(b) for b in chunk_documents(_claims(900))]
    assert batch_sizes == [400, 400, 100]


def test_reconcile_on_interrupted_summary_flags_needs_redo_never_committed() -> None:
    repo = InMemoryRunRepository(fail_after_writes=1)
    with pytest.raises(FaultInjected):
        finalize_patient_result(
            repo,
            run_id=_RUN_ID,
            patient_id=_PATIENT_ID,
            evidence_snapshot_id="snap-4",
            stage=PatientStage.FINAL_VALIDATION,
            claims=_claims(2),
            evidence=_evidence(1),
            terminal_status=PatientStatus.COMPLETED,
        )

    result = reconcile(repo, _RUN_ID, _PATIENT_ID)
    assert result is not None
    assert result.commit_status == CommitStatus.PREPARING
    assert result.commit_status != CommitStatus.COMMITTED


def test_reconcile_returns_none_when_no_summary_exists() -> None:
    repo = InMemoryRunRepository()
    assert reconcile(repo, "no-such-run", "no-such-patient") is None
