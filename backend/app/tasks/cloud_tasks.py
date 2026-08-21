"""Real `TaskQueue` adapter over the Cloud Tasks Admin SDK (`google-cloud-tasks`).

Thin by design, mirroring `app.storage.firestore_repo.FirestoreRunRepository`:
no business logic lives here beyond mapping a `RunTask` onto a Cloud Tasks
`CreateTask` call with an OIDC token attached, so Cloud Run can verify the
caller (`app.api.auth.require_oidc`) on delivery. All the dedup/idempotency
*contract* (`TaskQueue.enqueue` returns `True` for a fresh task, `False` for
a duplicate) is the same one `InMemoryTaskQueue` honors -- here it's Cloud
Tasks' own task-`name`-based dedup doing the work, not an in-memory set.

NOT exercised by the hermetic test suite (`make check` never talks to a real
Cloud Tasks queue) -- construction is deliberately lazy (the real gRPC
client is created on first `enqueue()`, not in `__init__`) so tests can
construct a `CloudTasksQueue` with dummy strings and assert it structurally
satisfies `TaskQueue` without touching the network. Every SDK call shape
below is taken from `research/gcp-notes.md` §3 (docs + installed SDK source,
read 2026-08-20) but is marked `# VERIFY-LIVE` for a fresh check against the
actual installed SDK version at real-deploy time, since Google ships this
SDK frequently and minor signature drift is plausible.
"""

from __future__ import annotations

import re

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.tasks.models import RunTask

__all__ = ["CloudTasksQueue"]

#: Cloud Tasks task names must match `[A-Za-z0-9_-]{1,500}` after the
#: `.../tasks/` prefix -- `RunTask.task_name` is `{run_id}:{patient_id}`,
#: which contains a `:` that isn't in that set, so it must be sanitized
#: before use as the literal task-name suffix.
_UNSAFE_TASK_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_task_name(task_name: str) -> str:
    """Map `RunTask.task_name` onto Cloud Tasks' allowed task-name charset."""
    return _UNSAFE_TASK_NAME_CHARS.sub("_", task_name)


class CloudTasksQueue:
    """Cloud Tasks-backed `TaskQueue` (satisfies the Protocol structurally).

    All of `project`, `location`, `queue`, `worker_url`,
    `service_account_email`, and `audience` are injected -- none are
    hard-coded, per spec. `worker_url` is this service's own
    `/tasks/process-patient` endpoint; `audience` is normally the same
    `run.app` base URL Cloud Run expects for OIDC verification
    (`research/gcp-notes.md` §2/§3).
    """

    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue: str,
        worker_url: str,
        service_account_email: str,
        audience: str,
    ) -> None:
        self._project = project
        self._location = location
        self._queue = queue
        self._worker_url = worker_url
        self._service_account_email = service_account_email
        self._audience = audience
        # Deferred: constructing `CloudTasksClient` opens a real gRPC channel
        # (network I/O). Keeping it lazy means `CloudTasksQueue(...)` is safe
        # to construct offline, e.g. for the hermetic
        # `isinstance(_, TaskQueue)` structural-Protocol test.
        self._client: tasks_v2.CloudTasksClient | None = None

    def _get_client(self) -> tasks_v2.CloudTasksClient:
        if self._client is None:
            # VERIFY-LIVE: `tasks_v2.CloudTasksClient()` picks up ADC exactly
            # like `firestore.Client()` does in `firestore_repo.py`.
            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def _build_task(self, task: RunTask, *, queue_path: str) -> tasks_v2.Task:
        """Build the Cloud Tasks `Task` for `task` (pure -- no network).

        The `Content-Type: application/json` header is REQUIRED: the worker
        endpoint (`POST /tasks/process-patient`) binds a Pydantic `RunTask`
        body, and FastAPI only parses the request body as JSON when the
        content type says so. Without this header Cloud Tasks delivers the
        bytes as `application/octet-stream` and FastAPI rejects the request
        with 422 before the handler ever runs.
        """
        task_name = f"{queue_path}/tasks/{_sanitize_task_name(task.task_name)}"
        return tasks_v2.Task(
            name=task_name,
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self._worker_url,
                headers={"Content-Type": "application/json"},
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._service_account_email,
                    audience=self._audience,
                ),
                body=task.model_dump_json().encode(),
            ),
        )

    def enqueue(self, task: RunTask) -> bool:
        """Enqueue `task` as a Cloud Tasks HTTP task with an OIDC token.

        Returns True on a fresh create, False if Cloud Tasks rejected it as
        a duplicate task name (`AlreadyExists`) -- honoring the same
        de-dup contract `InMemoryTaskQueue.enqueue` does (spec §46).
        """
        client = self._get_client()
        queue_path = client.queue_path(self._project, self._location, self._queue)
        cloud_task = self._build_task(task, queue_path=queue_path)

        try:
            # VERIFY-LIVE: `CreateTaskRequest(parent=..., task=...)` +
            # `client.create_task(...)` shape confirmed against
            # `research/gcp-notes.md` §3 (docs + installed 2.24.0+ SDK
            # source) as of Phase 18; re-check on any
            # `google-cloud-tasks` version bump before relying on it live.
            client.create_task(tasks_v2.CreateTaskRequest(parent=queue_path, task=cloud_task))
        except AlreadyExists:
            return False
        return True
