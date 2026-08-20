"""Idempotent task enqueue (spec §46).

`TaskQueue` is the Protocol a real Cloud Tasks-backed adapter will implement
in a later phase; `InMemoryTaskQueue` is the hermetic fake used here and in
tests. De-dup is keyed on `RunTask.task_name` (run_id:patient_id, excluding
attempt) so redelivering/re-enqueuing the same logical task never produces
a second queue entry.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.tasks.models import RunTask

__all__ = ["TaskQueue", "InMemoryTaskQueue"]


@runtime_checkable
class TaskQueue(Protocol):
    """Anything that can accept a `RunTask`, de-duping on `task_name`."""

    def enqueue(self, task: RunTask) -> bool:
        """Enqueue `task`.

        Returns True if this is a newly enqueued task, False if a task with
        the same `task_name` was already enqueued (no-op de-dup).
        """
        ...


class InMemoryTaskQueue:
    """Hermetic in-memory `TaskQueue`.

    Tracks seen `task_name`s for de-dup and keeps the accepted tasks (in
    enqueue order) in `.tasks` for test assertions.
    """

    def __init__(self) -> None:
        self._seen_task_names: set[str] = set()
        self.tasks: list[RunTask] = []

    def enqueue(self, task: RunTask) -> bool:
        if task.task_name in self._seen_task_names:
            return False
        self._seen_task_names.add(task.task_name)
        self.tasks.append(task)
        return True
