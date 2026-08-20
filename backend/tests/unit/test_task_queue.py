"""Tests for `app.tasks.queue` (spec §46): idempotent, de-duped enqueue."""

from __future__ import annotations

from app.tasks.models import RunTask
from app.tasks.queue import InMemoryTaskQueue


def test_duplicate_task_name_is_deduped() -> None:
    queue = InMemoryTaskQueue()
    first = RunTask(run_id="run-1", patient_id="pat-1", attempt=0)
    second = RunTask(run_id="run-1", patient_id="pat-1", attempt=1)

    assert queue.enqueue(first) is True
    assert queue.enqueue(second) is False

    assert len(queue.tasks) == 1
    assert queue.tasks[0] is first


def test_different_task_names_both_enqueue() -> None:
    queue = InMemoryTaskQueue()
    task_a = RunTask(run_id="run-1", patient_id="pat-1")
    task_b = RunTask(run_id="run-1", patient_id="pat-2")

    assert queue.enqueue(task_a) is True
    assert queue.enqueue(task_b) is True
    assert len(queue.tasks) == 2


def test_task_name_excludes_attempt() -> None:
    task = RunTask(run_id="run-1", patient_id="pat-1", attempt=7)
    assert task.task_name == "run-1:pat-1"
