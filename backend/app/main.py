"""FastAPI application entrypoint.

Phase 2 scope: app skeleton + a real `/health` check. Phase 18 (spec §76A.1)
adds `app.api.routes` -- the two OIDC-protected endpoints Cloud Scheduler
and Cloud Tasks call (`/enqueue-run`, `/tasks/process-patient`). TD-011
adds CORS for the PUBLIC, read-only `GET /runs/{run_id}` endpoint -- see
`_cors_allowed_origins` below for why this is scoped to that one route's
data being non-secret, not a blanket relaxation, and is orthogonal to the
OIDC endpoints' auth (CORS is a browser-side same-origin check; it has no
bearing on whether `require_oidc` accepts a request server-side).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.routes import router as api_router
from app.config import get_settings

DEFAULT_PORT = 8000


def _cors_allowed_origins() -> list[str]:
    """Parse `Settings.frontend_origin` (comma-separated) into an origin
    list for `CORSMiddleware`.

    Defaults to `["*"]` when unset: the only data any origin can read
    through CORS is the PUBLIC `GET /runs/{run_id}` payload (synthetic,
    non-secret run output) -- the OIDC-protected endpoints stay protected
    by `require_oidc` regardless of this setting, since CORS never governs
    server-side auth. Reads settings at call time (not import time), same
    pattern as every other `get_settings()` call site in this codebase, so
    a missing/invalid required env var never crashes import.
    """
    try:
        raw = get_settings().frontend_origin
    except ValidationError:
        return ["*"]
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="ChartPilot Backend")
app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> JSONResponse:
    """Report service health.

    Returns 200 with `{"status": "ok", ...}` when all required configuration
    can be loaded from the environment. Returns 503 naming the missing
    required field(s) when configuration fails to load. Never includes
    secret VALUES in the response — only field NAMES.
    """
    try:
        get_settings()
    except ValidationError as exc:
        missing_fields = sorted(
            {".".join(str(part) for part in error["loc"]) for error in exc.errors()}
        )
        body: dict[str, Any] = {
            "status": "error",
            "detail": "missing or invalid required configuration",
            "missing_fields": missing_fields,
        }
        return JSONResponse(status_code=503, content=body)

    return JSONResponse(status_code=200, content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", DEFAULT_PORT))
    uvicorn.run(app, host="0.0.0.0", port=port)  # noqa: S104 -- container-bound service
