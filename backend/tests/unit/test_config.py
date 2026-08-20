"""Unit tests for app.config.Settings / get_settings.

Verifies:
  - required config values are sourced from the environment (not hard-coded);
  - a missing required env var raises pydantic.ValidationError at load time,
    not at import time;
  - app/config.py and app/main.py contain no literal hard-coded project id,
    region, model id, or URL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

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


def test_settings_values_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing an env var changes the resulting Settings value."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GCP_PROJECT_ID", "my-custom-project-id")

    settings = Settings()

    assert settings.gcp_project_id == "my-custom-project-id"
    assert settings.gcp_region == "test-region-1"
    assert settings.model_a_id == "test-model-a"
    assert settings.model_b_id == "test-model-b"
    assert settings.gemini_api_key == "test-gemini-key"


def test_allow_synthetic_debug_logs_defaults_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional field must default to False and never be implicitly true."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("ALLOW_SYNTHETIC_DEBUG_LOGS", raising=False)

    settings = Settings()

    assert settings.allow_synthetic_debug_logs is False


def test_missing_required_field_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing required env var must raise, not silently default."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_memoized_and_clearable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_settings caches; cache_clear() forces a fresh env read."""
    _set_required_env(monkeypatch)
    get_settings.cache_clear()

    first = get_settings()
    monkeypatch.setenv("GCP_PROJECT_ID", "changed-after-first-call")
    second = get_settings()
    assert second.gcp_project_id == first.gcp_project_id  # still cached

    get_settings.cache_clear()
    third = get_settings()
    assert third.gcp_project_id == "changed-after-first-call"

    get_settings.cache_clear()


_APP_DIR = Path(__file__).resolve().parents[2] / "app"


@pytest.mark.parametrize("filename", ["config.py", "main.py"])
def test_no_hardcoded_ids_or_urls(filename: str) -> None:
    """app/config.py and app/main.py must not hard-code IDs, regions, or URLs.

    All such values must come from the environment, never from source code.
    """
    text = (_APP_DIR / filename).read_text(encoding="utf-8")

    assert "gemini-3" not in text, f"{filename} hard-codes a Gemini model id"
    assert "asia-south1" not in text, f"{filename} hard-codes a GCP region"
    assert "https://" not in text, f"{filename} hard-codes a URL"
