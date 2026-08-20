"""Tests for `app.tasks.orchestrator.process_patient` (spec §45/§46/§47):
idempotency, resumability, budget enforcement, and dead-lettering.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.gate.models import STAGE_ORDER, PatientStage, PatientStatus, is_terminal
from app.tasks.errors import RetryableStageError
from app.tasks.models import BudgetCounters, Checkpoint, ExecutionBudget, RunTask
from app.tasks.orchestrator import process_patient
from app.tasks.storage import InMemoryCheckpointStore

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
_RUNNABLE_STAGES = tuple(stage for stage in STAGE_ORDER if stage != PatientStage.QUEUED)


def _clock() -> datetime:
    return _NOW


def _noop(task: RunTask, counters: BudgetCounters) -> None:
    return None


def test_terminal_checkpoint_short_circuits_and_reruns_nothing() -> None:
    store = InMemoryCheckpointStore()
    existing = Checkpoint(
        run_id="run-1",
        patient_id="pat-1",
        status=PatientStatus.COMPLETED,
        current_stage=PatientStage.PERSISTED,
        completed_stages=_RUNNABLE_STAGES,
        attempt=0,
        model_call_count=0,
        evidence_call_count=0,
        fhir_page_count=0,
        checkpoint_version=1,
        last_success_at=_NOW,
    )
    store.save(existing)

    def _explode(task: RunTask, counters: BudgetCounters) -> None:
        raise AssertionError("stage runner must not be called for a terminal checkpoint")

    stage_runners = {stage: _explode for stage in _RUNNABLE_STAGES}
    task = RunTask(run_id="run-1", patient_id="pat-1", attempt=0)

    result = process_patient(
        task,
        store=store,
        budget=ExecutionBudget.default(),
        stage_runners=stage_runners,
        clock=_clock,
    )

    assert result == existing


def test_resume_from_checkpoint_does_not_rerun_completed_stages() -> None:
    store = InMemoryCheckpointStore()
    fetching_calls: list[int] = []

    def fetching_runner(task: RunTask, counters: BudgetCounters) -> None:
        fetching_calls.append(task.attempt)

    def normalizing_runner(task: RunTask, counters: BudgetCounters) -> None:
        if task.attempt == 0:
            raise RetryableStageError("transient normalize failure")

    stage_runners = {
        PatientStage.FETCHING: fetching_runner,
        PatientStage.NORMALIZING: normalizing_runner,
    }
    budget = ExecutionBudget.default()

    task0 = RunTask(run_id="run-2", patient_id="pat-2", attempt=0)
    with pytest.raises(RetryableStageError):
        process_patient(
            task0, store=store, budget=budget, stage_runners=stage_runners, clock=_clock
        )

    checkpoint_after_failure = store.get("run-2", "pat-2")
    assert checkpoint_after_failure is not None
    assert checkpoint_after_failure.completed_stages == (PatientStage.FETCHING,)
    assert checkpoint_after_failure.status == PatientStatus.RUNNING
    assert len(fetching_calls) == 1

    task1 = RunTask(run_id="run-2", patient_id="pat-2", attempt=1)
    result = process_patient(
        task1, store=store, budget=budget, stage_runners=stage_runners, clock=_clock
    )

    assert len(fetching_calls) == 1  # FETCHING was not re-run on resume
    assert result.status == PatientStatus.COMPLETED
    assert result.completed_stages == _RUNNABLE_STAGES


def test_budget_exceeded_marks_timed_out_at_last_completed_stage() -> None:
    store = InMemoryCheckpointStore()

    def bump_model_calls(task: RunTask, counters: BudgetCounters) -> None:
        counters.model_calls += 2

    stage_runners = {PatientStage.FETCHING: bump_model_calls}
    budget = ExecutionBudget(
        max_wall_clock_s=1_000_000.0,
        max_stage_iterations=100,
        max_model_calls=1,
        max_evidence_calls=100,
        max_fhir_pages=100,
        max_retries=3,
    )
    task = RunTask(run_id="run-3", patient_id="pat-3", attempt=0)

    result = process_patient(
        task, store=store, budget=budget, stage_runners=stage_runners, clock=_clock
    )

    assert result.status == PatientStatus.TIMED_OUT
    assert result.current_stage == PatientStage.FETCHING
    assert result.completed_stages == (PatientStage.FETCHING,)
    assert result.current_stage != PatientStage.PERSISTED


def test_attempt_beyond_max_retries_is_dead_lettered() -> None:
    store = InMemoryCheckpointStore()
    budget = ExecutionBudget.default()
    task = RunTask(run_id="run-4", patient_id="pat-4", attempt=budget.max_retries + 1)

    result = process_patient(task, store=store, budget=budget, stage_runners={}, clock=_clock)

    assert result.status == PatientStatus.DEAD_LETTER
    assert is_terminal(result.status)
    assert result.status not in (PatientStatus.COMPLETED, PatientStatus.PARTIAL)


def test_happy_path_reaches_persisted_and_completes() -> None:
    store = InMemoryCheckpointStore()
    stage_runners = {stage: _noop for stage in _RUNNABLE_STAGES}
    task = RunTask(run_id="run-5", patient_id="pat-5", attempt=0)

    result = process_patient(
        task,
        store=store,
        budget=ExecutionBudget.default(),
        stage_runners=stage_runners,
        clock=_clock,
    )

    assert result.status == PatientStatus.COMPLETED
    assert result.current_stage == PatientStage.PERSISTED
    assert result.completed_stages == _RUNNABLE_STAGES


def test_custom_finalize_overrides_default_completed_status() -> None:
    store = InMemoryCheckpointStore()
    stage_runners = {stage: _noop for stage in _RUNNABLE_STAGES}
    task = RunTask(run_id="run-6", patient_id="pat-6", attempt=0)

    def finalize(checkpoint: Checkpoint) -> PatientStatus:
        return PatientStatus.FLAGGED_FOR_REVIEW

    result = process_patient(
        task,
        store=store,
        budget=ExecutionBudget.default(),
        stage_runners=stage_runners,
        finalize=finalize,
        clock=_clock,
    )

    assert result.status == PatientStatus.FLAGGED_FOR_REVIEW
