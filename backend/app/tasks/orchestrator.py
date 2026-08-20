"""The durable per-patient processor (spec §45/§46/§47).

`process_patient` is idempotent (a terminal checkpoint short-circuits),
resumable (a non-terminal checkpoint resumes after its last completed
stage rather than restarting), and budgeted (a per-attempt `ExecutionBudget`
bounds wall clock, stage count, model calls, evidence calls, and FHIR
pages). It never talks to a real queue, database, or model -- all of that
is injected via `store`, `stage_runners`, and `clock`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.gate.models import STAGE_ORDER, PatientStage, PatientStatus, is_terminal
from app.tasks.errors import RetryableStageError
from app.tasks.models import BudgetCounters, Checkpoint, ExecutionBudget, RunTask
from app.tasks.storage import CheckpointStore

__all__ = ["StageRunner", "process_patient"]

#: Runs one stage of the pipeline for `task`, mutating `counters` as it
#: consumes budget (e.g. incrementing `model_calls`). May raise
#: `RetryableStageError` for a transient failure, or any other exception
#: for a non-retryable one.
StageRunner = Callable[[RunTask, BudgetCounters], None]


def _resume_state(
    existing: Checkpoint | None,
) -> tuple[PatientStage, list[PatientStage], int, int, int, int, datetime | None]:
    """Derive the resume point + carried-forward counts from `existing`.

    Returns (last_completed_stage, completed_stages_so_far, model_call_count,
    evidence_call_count, fhir_page_count, checkpoint_version, last_success_at).
    """
    if existing is None:
        return PatientStage.QUEUED, [], 0, 0, 0, 0, None
    last_completed = (
        existing.completed_stages[-1] if existing.completed_stages else PatientStage.QUEUED
    )
    return (
        last_completed,
        list(existing.completed_stages),
        existing.model_call_count,
        existing.evidence_call_count,
        existing.fhir_page_count,
        existing.checkpoint_version,
        existing.last_success_at,
    )


def process_patient(
    task: RunTask,
    *,
    store: CheckpointStore,
    budget: ExecutionBudget,
    stage_runners: dict[PatientStage, StageRunner],
    finalize: Callable[[Checkpoint], PatientStatus] | None = None,
    clock: Callable[[], datetime],
) -> Checkpoint:
    """Process one patient's pipeline run, resuming/budgeting/dead-lettering
    as needed (spec §45/§46/§47). Always returns the checkpoint it left the
    run in (terminal or, for a RetryableStageError, raises after saving).
    """
    existing = store.get(task.run_id, task.patient_id)

    # 1. Idempotency (§46): a terminal checkpoint is never reprocessed.
    if existing is not None and is_terminal(existing.status):
        return existing

    (
        last_completed,
        completed_stages,
        model_call_count,
        evidence_call_count,
        fhir_page_count,
        checkpoint_version,
        last_success_at,
    ) = _resume_state(existing)

    # 2. Dead-letter (§47): too many attempts is an explicit terminal state,
    # never presented as "no findings".
    if task.attempt > budget.max_retries:
        dead_letter = Checkpoint(
            run_id=task.run_id,
            patient_id=task.patient_id,
            status=PatientStatus.DEAD_LETTER,
            current_stage=last_completed,
            completed_stages=tuple(completed_stages),
            attempt=task.attempt,
            model_call_count=model_call_count,
            evidence_call_count=evidence_call_count,
            fhir_page_count=fhir_page_count,
            checkpoint_version=checkpoint_version + 1,
            last_success_at=last_success_at,
        )
        store.save(dead_letter)
        return dead_letter

    # 3. Resume (§45): iterate the remaining stages in canonical order,
    # starting right after the last completed one. QUEUED is a starting
    # marker, never a runnable stage.
    start_index = STAGE_ORDER.index(last_completed) + 1
    remaining_stages = STAGE_ORDER[start_index:]

    counters = BudgetCounters(
        model_calls=model_call_count,
        evidence_calls=evidence_call_count,
        fhir_pages=fhir_page_count,
    )
    start_time = clock()

    checkpoint = existing
    for stage in remaining_stages:
        counters.elapsed_s = (clock() - start_time).total_seconds()
        exceeded = counters.first_exceeded(budget)
        if exceeded is not None:
            timed_out = Checkpoint(
                run_id=task.run_id,
                patient_id=task.patient_id,
                status=PatientStatus.TIMED_OUT,
                current_stage=last_completed,
                completed_stages=tuple(completed_stages),
                attempt=task.attempt,
                model_call_count=counters.model_calls,
                evidence_call_count=counters.evidence_calls,
                fhir_page_count=counters.fhir_pages,
                checkpoint_version=checkpoint_version + 1,
                last_success_at=last_success_at,
            )
            store.save(timed_out)
            return timed_out

        counters.stage_iterations += 1
        runner = stage_runners.get(stage)
        if runner is not None:
            try:
                runner(task, counters)
            except RetryableStageError:
                retry_checkpoint = Checkpoint(
                    run_id=task.run_id,
                    patient_id=task.patient_id,
                    status=PatientStatus.RUNNING,
                    current_stage=last_completed,
                    completed_stages=tuple(completed_stages),
                    attempt=task.attempt,
                    model_call_count=counters.model_calls,
                    evidence_call_count=counters.evidence_calls,
                    fhir_page_count=counters.fhir_pages,
                    checkpoint_version=checkpoint_version + 1,
                    last_success_at=last_success_at,
                )
                store.save(retry_checkpoint)
                raise

        completed_stages.append(stage)
        last_completed = stage
        checkpoint_version += 1
        last_success_at = clock()
        checkpoint = Checkpoint(
            run_id=task.run_id,
            patient_id=task.patient_id,
            status=PatientStatus.RUNNING,
            current_stage=stage,
            completed_stages=tuple(completed_stages),
            attempt=task.attempt,
            model_call_count=counters.model_calls,
            evidence_call_count=counters.evidence_calls,
            fhir_page_count=counters.fhir_pages,
            checkpoint_version=checkpoint_version,
            last_success_at=last_success_at,
        )
        store.save(checkpoint)

    # 4. Terminal: PERSISTED has been reached (or was already, on resume of
    # an already-fully-staged non-terminal checkpoint). Compute the final
    # status and persist it.
    if checkpoint is None:
        raise RuntimeError(
            "process_patient reached PERSISTED with no checkpoint; "
            "STAGE_ORDER always has at least one runnable stage after QUEUED"
        )
    final_status = finalize(checkpoint) if finalize is not None else PatientStatus.COMPLETED
    final_checkpoint = checkpoint.model_copy(
        update={"status": final_status, "checkpoint_version": checkpoint.checkpoint_version + 1}
    )
    store.save(final_checkpoint)
    return final_checkpoint
