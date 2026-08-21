"""FastAPI application entrypoint.

Phase 2 scope: app skeleton + a real `/health` check. Phase 18 (spec §76A.1)
adds `app.api.routes` -- the two OIDC-protected endpoints Cloud Scheduler
and Cloud Tasks call (`/enqueue-run`, `/tasks/process-patient`).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.routes import router as api_router
from app.config import get_settings

DEFAULT_PORT = 8000

app = FastAPI(title="ChartPilot Backend")
app.include_router(api_router)


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
