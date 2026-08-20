"""Tests for `app.gate.patient_state` (spec §43): the patient run-state
machine's status derivation, stage monotonicity, and invariant checks.
"""

from __future__ import annotations

import pytest

from app.gate.errors import StateInvariantError
from app.gate.models import ClaimVerdict, CommitStatus, PatientStage, PatientStatus
from app.gate.patient_state import (
    PatientRunState,
    assert_state_invariants,
    can_advance_stage,
    derive_patient_status,
)

_ALL_VERIFIED = [ClaimVerdict.VERIFIED, ClaimVerdict.VERIFIED]


def test_all_verified_persisted_committed_is_completed() -> None:
    status = derive_patient_status(
        _ALL_VERIFIED,
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.COMPLETED


def test_empty_claim_list_persisted_committed_is_completed() -> None:
    """A zero-finding but fully-processed run is a legitimate COMPLETED,
    not a failure to process."""
    status = derive_patient_status(
        [],
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.COMPLETED


def test_preparing_commit_status_is_not_completed() -> None:
    status = derive_patient_status(
        _ALL_VERIFIED,
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.PREPARING,
    )
    assert status == PatientStatus.RUNNING


def test_completed_status_with_preparing_commit_violates_invariant() -> None:
    state = PatientRunState(
        status=PatientStatus.COMPLETED,
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.PREPARING,
    )
    with pytest.raises(StateInvariantError):
        assert_state_invariants(state)


def test_completed_status_requires_persisted_stage() -> None:
    state = PatientRunState(
        status=PatientStatus.COMPLETED,
        stage=PatientStage.FINAL_VALIDATION,
        commit_status=CommitStatus.COMMITTED,
    )
    with pytest.raises(StateInvariantError):
        assert_state_invariants(state)


def test_stage_before_persisted_is_not_completed() -> None:
    status = derive_patient_status(
        _ALL_VERIFIED,
        stage=PatientStage.FINAL_VALIDATION,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.RUNNING


def test_mix_of_verified_and_rejected_persisted_committed_is_partial() -> None:
    status = derive_patient_status(
        [ClaimVerdict.VERIFIED, ClaimVerdict.REJECTED],
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.PARTIAL


def test_any_requires_review_claim_flags_the_whole_run() -> None:
    status = derive_patient_status(
        [ClaimVerdict.VERIFIED, ClaimVerdict.REQUIRES_REVIEW],
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.FLAGGED_FOR_REVIEW


def test_any_conflicting_claim_flags_the_whole_run() -> None:
    status = derive_patient_status(
        [ClaimVerdict.VERIFIED, ClaimVerdict.CONFLICTING],
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
    )
    assert status == PatientStatus.FLAGGED_FOR_REVIEW


def test_explicit_failed_flag_wins() -> None:
    status = derive_patient_status(
        _ALL_VERIFIED,
        stage=PatientStage.PERSISTED,
        commit_status=CommitStatus.COMMITTED,
        failed=True,
    )
    assert status == PatientStatus.FAILED


def test_explicit_timed_out_flag_wins() -> None:
    status = derive_patient_status(
        [],
        stage=PatientStage.AI_REASONING,
        commit_status=CommitStatus.PREPARING,
        timed_out=True,
    )
    assert status == PatientStatus.TIMED_OUT


def test_explicit_dead_letter_flag_wins() -> None:
    status = derive_patient_status(
        [],
        stage=PatientStage.AI_REASONING,
        commit_status=CommitStatus.FAILED,
        dead_letter=True,
    )
    assert status == PatientStatus.DEAD_LETTER


def test_can_advance_stage_forward_is_true() -> None:
    assert can_advance_stage(PatientStage.FETCHING, PatientStage.NORMALIZING) is True


def test_can_advance_stage_backward_is_false() -> None:
    assert can_advance_stage(PatientStage.NORMALIZING, PatientStage.FETCHING) is False


def test_can_advance_stage_same_stage_is_true() -> None:
    assert can_advance_stage(PatientStage.FETCHING, PatientStage.FETCHING) is True
