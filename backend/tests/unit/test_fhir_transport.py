"""Tests for `app.fhir.transport.HttpFhirTransport`.

`http_get` and `sleep` are injected stubs -- these tests never touch the
network and never actually sleep.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.fhir.errors import FhirAuthError, FhirTransportError
from app.fhir.transport import HttpFhirTransport


class FakeResponse:
    """A minimal stand-in for an HTTP response object."""

    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict[str, Any]:
        return self._payload


class StubHttpGet:
    """Records calls and returns pre-scripted `FakeResponse`s in order."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> FakeResponse:
        self.calls.append(url)
        index = len(self.calls) - 1
        if index < len(self._responses):
            return self._responses[index]
        return self._responses[-1]


def _no_op_sleep_recorder() -> tuple[list[float], Callable[[float], None]]:
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return calls, sleep


def test_retries_on_429_then_succeeds() -> None:
    http_get = StubHttpGet(
        [
            FakeResponse(429),
            FakeResponse(429),
            FakeResponse(200, {"resourceType": "Bundle"}),
        ]
    )
    sleep_calls, sleep = _no_op_sleep_recorder()
    transport = HttpFhirTransport(
        "https://example.invalid/fhir/",
        http_get=http_get,
        sleep=sleep,
    )

    result = transport.fetch("Observation")

    assert result == {"resourceType": "Bundle"}
    assert len(http_get.calls) == 3
    assert len(sleep_calls) == 2


def test_401_raises_auth_error_with_exactly_one_attempt() -> None:
    http_get = StubHttpGet([FakeResponse(401)])
    _, sleep = _no_op_sleep_recorder()
    transport = HttpFhirTransport(
        "https://example.invalid/fhir/",
        http_get=http_get,
        sleep=sleep,
    )

    with pytest.raises(FhirAuthError):
        transport.fetch("Observation")

    assert len(http_get.calls) == 1


def test_persistent_500_raises_transport_error_after_max_attempts() -> None:
    http_get = StubHttpGet([FakeResponse(500)])
    _, sleep = _no_op_sleep_recorder()
    transport = HttpFhirTransport(
        "https://example.invalid/fhir/",
        http_get=http_get,
        sleep=sleep,
        max_attempts=4,
    )

    with pytest.raises(FhirTransportError):
        transport.fetch("Observation")

    assert len(http_get.calls) == 4


def test_404_raises_transport_error_with_exactly_one_attempt() -> None:
    http_get = StubHttpGet([FakeResponse(404)])
    _, sleep = _no_op_sleep_recorder()
    transport = HttpFhirTransport(
        "https://example.invalid/fhir/",
        http_get=http_get,
        sleep=sleep,
    )

    with pytest.raises(FhirTransportError):
        transport.fetch("Observation")

    assert len(http_get.calls) == 1
