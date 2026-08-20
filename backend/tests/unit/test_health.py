"""Unit tests for GET /health.

Hermetic: no network calls. Required env vars are set/cleared via
monkeypatch, and the memoized settings cache is cleared before each test so
tests don't leak state into one another.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_health_returns_200_when_config_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_returns_503_when_required_var_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert "gemini_api_key" in body["missing_fields"]
    # never leak a secret value in the body
    assert "test-gemini-key" not in response.text


def test_health_503_body_does_not_leak_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value-should-not-appear")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 503
    assert "super-secret-value-should-not-appear" not in response.text
    assert "gcp_project_id" in response.json()["missing_fields"]
