"""Tests for the OIDC-protected HTTP endpoints (spec §76A.1):
`POST /enqueue-run` and `POST /tasks/process-patient`.

Hermetic: no network. The real `require_oidc` dependency is exercised
directly for the "no/invalid bearer token" paths (it rejects before ever
calling the network-touching verifier), and overridden via
`app.dependency_overrides` for the "accepted" paths so the real Google
verification call is never reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.api.auth import require_oidc
from app.config import get_settings
from app.gate.models import STAGE_ORDER, PatientStage, PatientStatus
from app.main import app
from app.tasks.appointments import InMemoryAppointmentSource
from app.tasks.errors import RetryableStageError
from app.tasks.models import BudgetCounters, Checkpoint, ExecutionBudget, RunTask
from app.tasks.orchestrator import process_patient
from app.tasks.queue import InMemoryTaskQueue
from app.tasks.storage import InMemoryCheckpointStore

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
    "OIDC_AUDIENCE": "https://chartpilot-test-abc123-el.a.run.app",
}

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _accept_oidc() -> dict[str, str]:
    return {"sub": "test-caller"}


def _reject_oidc() -> dict[str, str]:
    raise HTTPException(status_code=401, detail="invalid OIDC token")


def _noop(task: RunTask, counters: BudgetCounters) -> None:
    return None


# --------------------------------------------------------------------------
# /health regression (must not break with the new router mounted)
# --------------------------------------------------------------------------


def test_health_still_ok_with_new_router_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --------------------------------------------------------------------------
# require_oidc: reject paths (real dependency, no override needed)
# --------------------------------------------------------------------------


def test_process_patient_missing_bearer_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post("/tasks/process-patient", json=task.model_dump(mode="json"))

    assert response.status_code == 401


def test_process_patient_malformed_authorization_header_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "not-a-bearer-token"},
    )

    assert response.status_code == 401


def test_process_patient_fails_closed_when_audience_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "Bearer some-token"},
    )

    assert response.status_code == 401


def test_process_patient_rejecting_verifier_override_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _reject_oidc
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------
# /tasks/process-patient: accepted path + idempotent duplicate delivery
# --------------------------------------------------------------------------


def test_process_patient_accepted_invokes_handler_with_parsed_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc

    received: list[RunTask] = []

    def fake_handler(task: RunTask) -> Checkpoint:
        received.append(task)
        return Checkpoint(
            run_id=task.run_id,
            patient_id=task.patient_id,
            status=PatientStatus.COMPLETED,
            current_stage=PatientStage.PERSISTED,
            completed_stages=tuple(s for s in STAGE_ORDER if s != PatientStage.QUEUED),
            attempt=task.attempt,
            model_call_count=0,
            evidence_call_count=0,
            fhir_page_count=0,
            checkpoint_version=1,
            last_success_at=_NOW,
        )

    app.dependency_overrides[api_routes.get_process_patient_handler] = lambda: fake_handler
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(received) == 1
    assert received[0].run_id == "run-1"
    assert received[0].patient_id == "pat-1"


def test_process_patient_duplicate_delivery_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real `process_patient` (backed by a shared `InMemoryCheckpointStore`)
    wired as the handler: two identical POSTs run the stage exactly once and
    both return 200 with the same terminal checkpoint (spec §46)."""
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc

    store = InMemoryCheckpointStore()
    stage_call_count = 0

    def _counting_stage(task: RunTask, counters: BudgetCounters) -> None:
        nonlocal stage_call_count
        stage_call_count += 1

    stage_runners = {
        stage: _counting_stage for stage in STAGE_ORDER if stage != PatientStage.QUEUED
    }

    def real_handler(task: RunTask) -> Checkpoint:
        return process_patient(
            task,
            store=store,
            budget=ExecutionBudget.default(),
            stage_runners=stage_runners,
            clock=lambda: _NOW,
        )

    app.dependency_overrides[api_routes.get_process_patient_handler] = lambda: real_handler
    client = TestClient(app)
    task = RunTask(run_id="run-1", patient_id="pat-1")
    body = task.model_dump(mode="json")
    headers = {"Authorization": "Bearer good-token"}

    first = client.post("/tasks/process-patient", json=body, headers=headers)
    second = client.post("/tasks/process-patient", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "completed"
    # The stage runners only ran once: the second delivery's terminal
    # checkpoint short-circuited process_patient before touching them again.
    assert stage_call_count == len(stage_runners)


def test_process_patient_retryable_stage_error_surfaces_as_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient stage failure must NOT be swallowed as a 200 -- Cloud
    Tasks relies on a non-2xx response to redeliver with attempt + 1."""
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc

    store = InMemoryCheckpointStore()

    def _explode(task: RunTask, counters: BudgetCounters) -> None:
        raise RetryableStageError("transient failure")

    stage_runners = {stage: _explode for stage in STAGE_ORDER if stage != PatientStage.QUEUED}

    def real_handler(task: RunTask) -> Checkpoint:
        return process_patient(
            task,
            store=store,
            budget=ExecutionBudget.default(),
            stage_runners=stage_runners,
            clock=lambda: _NOW,
        )

    app.dependency_overrides[api_routes.get_process_patient_handler] = lambda: real_handler
    client = TestClient(app, raise_server_exceptions=False)
    task = RunTask(run_id="run-1", patient_id="pat-1")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code >= 500


# --------------------------------------------------------------------------
# /enqueue-run
# --------------------------------------------------------------------------


def test_enqueue_run_accepted_uses_injected_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc

    source = InMemoryAppointmentSource({date(2026, 8, 21): ["pat-1", "pat-2"]})
    queue = InMemoryTaskQueue()
    app.dependency_overrides[api_routes.get_appointment_source] = lambda: source
    app.dependency_overrides[api_routes.get_queue] = lambda: queue
    app.dependency_overrides[api_routes.get_clock] = lambda: lambda: _NOW

    client = TestClient(app)
    response = client.post(
        "/enqueue-run",
        json={"run_id": "run-1"},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-1"
    assert body["patient_count"] == 2
    assert body["enqueued"] == 2
    assert body["success"] is True
    assert len(queue.tasks) == 2


def test_enqueue_run_missing_bearer_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)

    response = client.post("/enqueue-run", json={"run_id": "run-1"})

    assert response.status_code == 401
