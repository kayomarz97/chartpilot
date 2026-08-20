"""Nightly fan-out: enqueue one `RunTask` per patient with tomorrow's
appointment (spec §48).

A zero-appointment night is a legitimate, successful run -- there was
nothing to enqueue, not a failure to enqueue anything.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.tasks.appointments import AppointmentSource, tomorrow_ist
from app.tasks.models import RunTask
from app.tasks.queue import TaskQueue

__all__ = ["EnqueueResult", "enqueue_run"]


class EnqueueResult(BaseModel):
    """The outcome of one nightly fan-out (spec §48)."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    patient_count: int
    enqueued: int
    success: bool


def enqueue_run(
    *,
    run_id: str,
    appointment_source: AppointmentSource,
    queue: TaskQueue,
    clock: Callable[[], datetime],
) -> EnqueueResult:
    """Enqueue one `RunTask` per patient appointed for tomorrow (IST).

    De-dup (same `run_id`/`patient_id` enqueued twice) is handled by
    `queue.enqueue` itself; `enqueued` here counts only newly-accepted
    tasks. Zero patients found is `success=True` -- a valid, successful
    run, not an error.
    """
    day = tomorrow_ist(clock())
    patient_ids = appointment_source.patients_for_day(day)

    enqueued = 0
    for patient_id in patient_ids:
        task = RunTask(run_id=run_id, patient_id=patient_id)
        if queue.enqueue(task):
            enqueued += 1

    return EnqueueResult(
        run_id=run_id,
        patient_count=len(patient_ids),
        enqueued=enqueued,
        success=True,
    )
