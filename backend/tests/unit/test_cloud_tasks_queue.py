"""Tests for `app.tasks.cloud_tasks.CloudTasksQueue` (spec §76A.1).

Hermetic: construction must never touch the network (the real gRPC client
is created lazily, on first `.enqueue()`), so these tests only exercise
construction + the structural `TaskQueue` Protocol check and the task-name
sanitizer -- never `.enqueue()` itself, which would require a real Cloud
Tasks queue.
"""

from __future__ import annotations

from app.tasks.cloud_tasks import CloudTasksQueue, _sanitize_task_name
from app.tasks.queue import TaskQueue


def _make_queue() -> CloudTasksQueue:
    return CloudTasksQueue(
        project="test-project-id",
        location="test-region-1",
        queue="test-queue",
        worker_url="https://chartpilot-test.a.run.app/tasks/process-patient",
        service_account_email="test-invoker@test-project-id.iam.gserviceaccount.com",
        audience="https://chartpilot-test.a.run.app",
    )


def test_cloud_tasks_queue_satisfies_task_queue_protocol() -> None:
    queue = _make_queue()
    assert isinstance(queue, TaskQueue)


def test_cloud_tasks_queue_construction_does_not_create_a_client() -> None:
    """Client construction is deferred to first `.enqueue()` -- constructing
    `CloudTasksQueue` alone must be safe with sockets disabled."""
    queue = _make_queue()
    assert queue._client is None


def test_sanitize_task_name_maps_colon_to_allowed_charset() -> None:
    assert _sanitize_task_name("run-1:pat-1") == "run-1_pat-1"


def test_sanitize_task_name_is_idempotent_on_already_safe_names() -> None:
    assert _sanitize_task_name("already-safe_name123") == "already-safe_name123"
