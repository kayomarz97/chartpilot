"""Transports for the FHIR read layer.

A transport's only job is: given a reference (a relative FHIR url or a local
fixture filename), return the parsed JSON body. Everything above this layer
(`app.fhir.client.FhirClient`) is transport-agnostic.

Two transports are provided:
  - `LocalFixtureTransport`: reads Bundle/resource JSON from a local
    directory of fixture files. Used in Phase 3 and in tests.
  - `HttpFhirTransport`: the future live-FHIR-server path. Its HTTP call is
    injected (`http_get`) so it can be exercised hermetically in tests with a
    stub -- this module never performs real network I/O itself.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.fhir.errors import FhirAuthError, FhirTransportError, MalformedBundleError

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUS_CODES = frozenset({401, 403})


@runtime_checkable
class FhirTransport(Protocol):
    """Anything that can fetch a FHIR Bundle or resource by reference."""

    def fetch(self, ref: str) -> dict[str, Any]:
        """Fetch `ref` and return its parsed JSON body.

        Raises `app.fhir.errors.FhirError` subclasses on any failure; never
        raises a bare/unrelated exception (e.g. OSError, JSONDecodeError).
        """
        ...


@runtime_checkable
class HttpResponse(Protocol):
    """The minimal shape `HttpFhirTransport` needs from an HTTP response."""

    status_code: int

    def json(self) -> dict[str, Any]:
        """Parse and return the response body as JSON."""
        ...


class LocalFixtureTransport:
    """Reads FHIR Bundles/resources from local JSON fixture files.

    `ref` is a fixture filename relative to `base_dir` (e.g. "page1.json").
    Path traversal outside `base_dir` is rejected.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()

    def fetch(self, ref: str) -> dict[str, Any]:
        """Read and JSON-parse the fixture file named by `ref`.

        Raises:
            FhirTransportError: the file does not exist, escapes `base_dir`,
                or cannot be read.
            MalformedBundleError: the file exists but is not valid JSON.
        """
        candidate = (self._base_dir / ref).resolve()
        try:
            candidate.relative_to(self._base_dir)
        except ValueError as exc:
            raise FhirTransportError(f"ref escapes fixture base_dir: {ref!r}") from exc

        if not candidate.is_file():
            raise FhirTransportError(f"fixture not found: {ref!r}")

        try:
            raw = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise FhirTransportError(f"failed to read fixture {ref!r}: {exc}") from exc

        try:
            parsed: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedBundleError(f"invalid JSON in fixture {ref!r}: {exc}") from exc

        return parsed


class HttpFhirTransport:
    """Fetches FHIR Bundles/resources over HTTP from a live FHIR server.

    The HTTP call itself is injected via `http_get` so this class can be
    unit-tested with a stub and never needs real network access. A default
    real implementation (backed by `httpx`) can be built separately and
    passed in as `http_get` for production use.
    """

    def __init__(
        self,
        base_url: str,
        *,
        http_get: Callable[[str], HttpResponse],
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
        backoff_base: float = 0.5,
    ) -> None:
        self._base_url = base_url
        self._http_get = http_get
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base

    def fetch(self, ref: str) -> dict[str, Any]:
        """Fetch `ref` over HTTP, retrying transient failures.

        `ref` is resolved against `base_url` unless it already looks
        absolute (starts with "http").

        Status code handling:
          - 200: return the parsed JSON body.
          - 401/403: raise `FhirAuthError` immediately, no retry.
          - 429 or 5xx (500/502/503/504): retry with exponential backoff
            (`backoff_base * 2**attempt`) up to `max_attempts` total tries;
            raise `FhirTransportError` if still failing after the last try.
          - any other status: raise `FhirTransportError` immediately, no
            retry.
        """
        url = ref if ref.startswith("http") else self._base_url + ref

        attempts = 0
        last_status: int | None = None
        while attempts < self._max_attempts:
            attempts += 1
            response = self._http_get(url)
            status = response.status_code

            if status == 200:
                return response.json()

            if status in _AUTH_STATUS_CODES:
                raise FhirAuthError(
                    f"authentication failed fetching {ref!r}: status {status} (attempts={attempts})"
                )

            last_status = status
            if status not in _RETRYABLE_STATUS_CODES:
                raise FhirTransportError(
                    f"non-retryable status fetching {ref!r}: status {status} (attempts={attempts})"
                )

            if attempts < self._max_attempts:
                self._sleep(self._backoff_base * (2 ** (attempts - 1)))

        raise FhirTransportError(
            f"exhausted retries fetching {ref!r}: last status {last_status} (attempts={attempts})"
        )
