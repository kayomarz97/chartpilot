"""Tests for the PUBLIC, read-only `GET /runs/{run_id}` endpoint and its
CORS enablement (TD-011).

Hermetic: `get_run_repository` is overridden with an in-memory repo, so no
real Firestore connection is ever attempted.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.config import get_settings
from app.main import app
from app.storage.inmemory import InMemoryRunRepository

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
}


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


def _repo_with_two_presentations() -> InMemoryRunRepository:
    repo = InMemoryRunRepository()
    repo.upsert_presentation(
        "run-1",
        "patient-a",
        {
            "patientId": "patient-a",
            "patientName": "Rosa Alvarez",
            "status": "COMPLETED",
            "stage": "persisted",
            "findings": [],
            "timeline": [],
            "labs": [],
        },
    )
    repo.upsert_presentation(
        "run-1",
        "patient-b",
        {
            "patientId": "patient-b",
            "patientName": "John Doe",
            "status": "FLAGGED_FOR_REVIEW",
            "stage": "persisted",
            "findings": [],
            "timeline": [],
            "labs": [],
        },
    )
    return repo


def test_get_run_presentations_returns_persisted_payloads() -> None:
    repo = _repo_with_two_presentations()
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    client = TestClient(app)

    response = client.get("/runs/run-1")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-1"
    assert body["generated_at"] is None
    assert len(body["patients"]) == 2
    assert {p["patientId"] for p in body["patients"]} == {"patient-a", "patient-b"}


def test_get_run_presentations_unknown_run_returns_empty_list_not_404() -> None:
    repo = InMemoryRunRepository()
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    client = TestClient(app)

    response = client.get("/runs/does-not-exist")

    assert response.status_code == 200
    assert response.json()["patients"] == []


def test_get_run_presentations_requires_no_auth() -> None:
    """PUBLIC endpoint: no Authorization header needed, unlike
    /enqueue-run and /tasks/process-patient (require_oidc)."""
    repo = _repo_with_two_presentations()
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    client = TestClient(app)

    response = client.get("/runs/run-1")

    assert response.status_code == 200


def test_cors_header_present_on_get_runs() -> None:
    repo = InMemoryRunRepository()
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    client = TestClient(app)

    response = client.get("/runs/run-1", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


# --------------------------------------------------------------------------
# Regression: /health and the OIDC-protected endpoints still work with the
# new public router + CORS middleware mounted.
# --------------------------------------------------------------------------


def test_health_still_ok_with_cors_middleware_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_process_patient_still_requires_oidc_with_cors_middleware_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    response = client.post("/tasks/process-patient", json={"run_id": "r", "patient_id": "p"})
    assert response.status_code == 401


def test_enqueue_run_still_requires_oidc_with_cors_middleware_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)
    response = client.post("/enqueue-run", json={"run_id": "r"})
    assert response.status_code == 401
