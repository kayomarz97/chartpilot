"""Shared pytest fixtures.

Hermeticity guard: the test suite must NEVER read a developer's local
`backend/.env` (which now exists to hold a real GEMINI_API_KEY for live
checks). `app.config.Settings` is configured with `env_file=".env"`, so
without this fixture the mere presence of that file would leak real config
into tests that deliberately exercise the *missing-config* path (e.g. the
`/health` 503 tests). We disable env-file loading for every test so config
comes only from the (monkeypatched) process environment, exactly as it does
in CI where no `.env` exists.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Disable `.env` loading and clear the settings cache around each test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
