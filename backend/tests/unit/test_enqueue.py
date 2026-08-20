"""Tests for `app.tasks.enqueue` (spec §48): nightly fan-out."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.tasks.appointments import InMemoryAppointmentSource
from app.tasks.enqueue import enqueue_run
from app.tasks.queue import InMemoryTaskQueue

_NOW_UTC = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)  # tomorrow IST = 2026-08-21


def _clock() -> datetime:
    return _NOW_UTC


def test_enqueue_run_enqueues_one_task_per_appointed_patient() -> None:
    source = InMemoryAppointmentSource({date(2026, 8, 21): ["pat-1", "pat-2", "pat-3"]})
    queue = InMemoryTaskQueue()

    result = enqueue_run(run_id="run-1", appointment_source=source, queue=queue, clock=_clock)

    assert result.patient_count == 3
    assert result.enqueued == 3
    assert result.success is True
    assert len(queue.tasks) == 3
    assert {t.patient_id for t in queue.tasks} == {"pat-1", "pat-2", "pat-3"}
    assert all(t.run_id == "run-1" for t in queue.tasks)


def test_enqueue_run_zero_appointments_is_a_successful_run() -> None:
    source = InMemoryAppointmentSource({})
    queue = InMemoryTaskQueue()

    result = enqueue_run(run_id="run-1", appointment_source=source, queue=queue, clock=_clock)

    assert result.patient_count == 0
    assert result.enqueued == 0
    assert result.success is True
    assert len(queue.tasks) == 0
