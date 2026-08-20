"""Application configuration.

All configuration is sourced from environment variables (and, for local
development, a `.env` file). Nothing here may contain a hard-coded project
id, region, model id, API key, or URL — those are secrets/environment-specific
values and MUST come from the environment only (spec: no hard-coded IDs).

Required fields have NO defaults: if they are missing, constructing
`Settings()` raises a `pydantic.ValidationError`. Callers (e.g. the health
check in `app.main`) are expected to catch that error rather than let a
missing environment variable crash the whole process at import time.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the environment.

    Required (no default -> missing value raises ValidationError at
    instantiation time, not at import time):
      - gcp_project_id
      - gcp_region
      - model_a_id
      - model_b_id
      - gemini_api_key

    Optional:
      - allow_synthetic_debug_logs: must default to False and must never be
        implicitly enabled (spec §54).
      - display_timezone: IANA name used to render coarse-precision
        clinical timestamps for humans; defaults to "Asia/Kolkata". This is
        a display convention, not a secret/environment-specific value.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    gcp_project_id: str
    gcp_region: str
    model_a_id: str
    model_b_id: str
    gemini_api_key: str

    allow_synthetic_debug_logs: bool = False
    display_timezone: str = "Asia/Kolkata"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load (and memoize) Settings from the environment.

    Importing this module never raises, even if required environment
    variables are missing — construction is deferred until this function is
    actually called, so callers (e.g. a health check) can catch the
    `pydantic.ValidationError` themselves and report which fields are
    missing, instead of crashing app startup / module import.

    Tests that mutate the environment must clear the memoized value first
    via `get_settings.cache_clear()` (provided by `functools.lru_cache`).
    """
    return Settings()
