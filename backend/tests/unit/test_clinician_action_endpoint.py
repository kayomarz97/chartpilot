"""Tests for the OIDC-protected `POST /runs/{run_id}/patients/{patient_id}/
clinician-action` endpoint (Phase B, spec §53).

Hermetic: `get_run_repository` is overridden with an in-memory repo and
`require_oidc` is overridden to accept, so no real Firestore/Google
verification call is ever attempted.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.api.auth import require_oidc
from app.config import get_settings
from app.main import app
from app.storage.inmemory import InMemoryRunRepository
from app.storage.models import clinician_actions_collection_path

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
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


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "claim_id": "claim-1",
        "action": "confirm",
        "note": "",
        "verdict_shown": "REQUIRES_REVIEW",
        "action_id": "patient-1:claim-1",
    }
    payload.update(overrides)
    return payload


def _client_with_overrides(
    monkeypatch: pytest.MonkeyPatch, repo: InMemoryRunRepository
) -> TestClient:
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    app.dependency_overrides[api_routes.get_clock] = lambda: lambda: _NOW
    return TestClient(app)


def test_missing_bearer_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)

    response = client.post("/runs/run-1/patients/patient-1/clinician-action", json=_body())

    assert response.status_code == 401


def test_persists_clinician_action_to_the_right_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryRunRepository()
    client = _client_with_overrides(monkeypatch, repo)

    response = client.post(
        "/runs/run-1/patients/patient-1/clinician-action",
        json=_body(),
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action_id"] == "patient-1:claim-1"
    assert body["run_id"] == "run-1"
    assert body["patient_id"] == "patient-1"
    assert body["claim_id"] == "claim-1"
    assert body["action"] == "confirm"
    assert body["trusted"] is False
    assert body["verdict_shown"] == "REQUIRES_REVIEW"
    assert body["recorded_at"] == "2026-08-20T12:00:00Z"

    stored = dict(repo.read_documents(clinician_actions_collection_path("run-1", "patient-1")))
    assert set(stored.keys()) == {"patient-1:claim-1"}
    assert stored["patient-1:claim-1"]["action"] == "confirm"
    assert stored["patient-1:claim-1"]["trusted"] is False


def test_repost_with_same_action_id_is_idempotent_overwrite_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryRunRepository()
    client = _client_with_overrides(monkeypatch, repo)
    headers = {"Authorization": "Bearer good-token"}

    first = client.post(
        "/runs/run-1/patients/patient-1/clinician-action",
        json=_body(action="confirm"),
        headers=headers,
    )
    second = client.post(
        "/runs/run-1/patients/patient-1/clinician-action",
        json=_body(action="override", note="changed my mind"),
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200

    stored = dict(repo.read_documents(clinician_actions_collection_path("run-1", "patient-1")))
    # Same action_id -> one doc, overwritten with the latest submission.
    assert len(stored) == 1
    assert stored["patient-1:claim-1"]["action"] == "override"
    assert stored["patient-1:claim-1"]["note"] == "changed my mind"


def test_note_is_stored_with_trusted_false(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryRunRepository()
    client = _client_with_overrides(monkeypatch, repo)

    response = client.post(
        "/runs/run-1/patients/patient-1/clinician-action",
        json=_body(action="correct", note="actually potassium was drawn hemolyzed"),
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["note"] == "actually potassium was drawn hemolyzed"
    assert body["trusted"] is False
