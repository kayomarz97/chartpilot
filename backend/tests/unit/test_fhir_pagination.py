"""Tests for `app.fhir.client.FhirClient` pagination, loops, and limits.

Uses `LocalFixtureTransport` pointed at `tests/fixtures/fhir/` -- no
network, no real FHIR server.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.fhir.client import FhirClient
from app.fhir.errors import (
    FhirPaginationError,
    FhirResourceLimitError,
    MalformedBundleError,
)
from app.fhir.transport import LocalFixtureTransport

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "fhir"


def _client(*, max_pages: int = 50, max_resources: int = 5000) -> FhirClient:
    transport = LocalFixtureTransport(FIXTURES_DIR)
    return FhirClient(transport, max_pages=max_pages, max_resources=max_resources)


def test_traverses_full_page_chain_and_terminates() -> None:
    client = _client()
    resources = client.fetch_all("page1.json")
    assert len(resources) == 5
    ids = [r["id"] for r in resources]
    assert ids == ["obs-1", "obs-2", "obs-3", "obs-4", "obs-5"]


def test_single_page_returns_its_resources_with_no_next_link() -> None:
    client = _client()
    resources = client.fetch_all("single.json")
    assert len(resources) == 2
    assert {r["id"] for r in resources} == {"pat-1", "obs-single-1"}


def test_loop_raises_pagination_error() -> None:
    client = _client()
    with pytest.raises(FhirPaginationError):
        client.fetch_all("loop_a.json")


def test_malformed_missing_resource_type_raises() -> None:
    client = _client()
    with pytest.raises(MalformedBundleError):
        client.fetch_all("malformed_missing_type.json")


def test_malformed_bad_link_raises() -> None:
    client = _client()
    with pytest.raises(MalformedBundleError):
        client.fetch_all("malformed_bad_link.json")


def test_max_pages_exceeded_raises_pagination_error() -> None:
    client = _client(max_pages=2)
    with pytest.raises(FhirPaginationError):
        client.fetch_all("page1.json")


def test_max_resources_exceeded_raises_resource_limit_error() -> None:
    client = _client(max_resources=2)
    with pytest.raises(FhirResourceLimitError):
        client.fetch_all("page1.json")
