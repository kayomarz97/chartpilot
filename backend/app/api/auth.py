"""OIDC bearer-token verification for Cloud Tasks / Cloud Scheduler callers
(spec §76A.1).

Cloud Run rejects unauthenticated invocations at the platform level (the
service is deployed `--no-allow-unauthenticated`), but the app layer must
independently verify the attached Google-signed OIDC ID token: issuer must
be one of Google's own OIDC issuers, and audience must equal this service's
own `run.app` URL (`Settings.oidc_audience`) -- never a custom domain, per
`research/gcp-notes.md` §2. Verification itself is delegated to
`google.oauth2.id_token.verify_oauth2_token`, which already enforces the
issuer allowlist (`accounts.google.com` / `https://accounts.google.com`)
internally; we additionally pass `audience=` so it enforces that too.

The module-level `_verifier` is the sole seam a real network call crosses
(`# VERIFY-LIVE` below). Tests may either monkeypatch `_verifier` directly
or override the `require_oidc` FastAPI dependency wholesale via
`app.dependency_overrides[require_oidc]` -- both are supported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import Header, HTTPException
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from app.config import get_settings

__all__ = ["require_oidc", "TokenVerifier"]

#: Verifies `id_token` against `audience`, returning the decoded claims on
#: success. Must raise `ValueError` or `google.auth.exceptions.GoogleAuthError`
#: (or a subclass) on any verification failure -- `require_oidc` catches
#: exactly those and turns them into a 401.
TokenVerifier = Callable[[str, str], Mapping[str, Any]]


def _verify_google_oidc_token(token: str, audience: str) -> Mapping[str, Any]:
    """Verify a real Google-signed OIDC ID token.

    # VERIFY-LIVE: `google.oauth2.id_token.verify_oauth2_token(id_token,
    # request, audience=...)` signature confirmed directly against the
    # installed `google-auth` package source
    # (`google/oauth2/id_token.py`, `verify_oauth2_token`) as of Phase 18;
    # re-check on any `google-auth` version bump before relying on it live.
    # It performs a live HTTP fetch of Google's public certs via `request`
    # (network I/O) -- never invoked by the hermetic test suite.
    """
    request = google_auth_requests.Request()
    # `verify_oauth2_token` ships without type annotations in the installed
    # google-auth source -- explicitly typed here rather than letting `Any`
    # leak out (mypy --strict forbids both the untyped call and an implicit
    # `Any` return).
    claims: dict[str, Any] = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        token, request, audience=audience
    )
    return claims


_verifier: TokenVerifier = _verify_google_oidc_token


def _extract_bearer_token(authorization: str | None) -> str:
    """Pull the token out of `Authorization: Bearer <token>`, or fail with 401."""
    if authorization is None:
        raise HTTPException(status_code=401, detail="missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'")
    return token


def require_oidc(authorization: str | None = Header(default=None)) -> Mapping[str, Any]:
    """FastAPI dependency: require and verify a Google-signed OIDC bearer token.

    Fails CLOSED: if `Settings.oidc_audience` is not configured, every
    request is rejected outright -- an unset audience must never be treated
    as "accept anything" (spec §76A.1). Resolves the module-level
    `_verifier` at call time (not import time) so `monkeypatch.setattr` on
    this module's `_verifier` takes effect per-test; alternatively, override
    this whole dependency via `app.dependency_overrides[require_oidc]`.
    """
    settings = get_settings()
    if not settings.oidc_audience:
        raise HTTPException(status_code=401, detail="OIDC audience not configured")

    token = _extract_bearer_token(authorization)
    try:
        return _verifier(token, settings.oidc_audience)
    except (ValueError, google_auth_exceptions.GoogleAuthError) as exc:
        raise HTTPException(status_code=401, detail="invalid OIDC token") from exc
