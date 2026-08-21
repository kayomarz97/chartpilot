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
      - oidc_audience: the audience Cloud Tasks/Scheduler OIDC ID tokens
        must carry for `app.api.auth.require_oidc` to accept them --
        normally this service's own `run.app` URL. Optional so existing
        hermetic `/health` tests (which don't set it) keep passing at
        import/startup time; `require_oidc` itself fails CLOSED (rejects
        every request) when it is unset, rather than silently allowing
        unauthenticated access (spec §76A.1).
      - tasks_queue: the Cloud Tasks queue id (not a full resource path)
        `app.api.composition.build_live_queue` targets. Optional for the
        same reason as `oidc_audience` above; `build_live_queue` itself
        fails CLOSED (raises `RuntimeError`) when it is unset.
      - worker_url: this service's own `/tasks/process-patient` URL, given
        to Cloud Tasks as the HTTP target for every enqueued task.
      - tasks_invoker_sa: the service account email Cloud Tasks uses to mint
        the OIDC token attached to each task, so Cloud Run's
        `require_oidc` can verify the caller.
      - firestore_database: the named Firestore database (spec §44 uses an
        explicit regional database, never the `(default)` one) that
        `app.api.composition._build_run_repository` connects
        `FirestoreRunRepository` to.
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
    oidc_audience: str | None = None
    tasks_queue: str | None = None
    worker_url: str | None = None
    tasks_invoker_sa: str | None = None
    firestore_database: str | None = None


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
