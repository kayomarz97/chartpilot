"""Tests for `app.evidence.pubmed`.

`http_get` is an injected stub reading recorded fixture JSON/XML -- these
tests never touch the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.evidence.budget import CallBudget
from app.evidence.errors import EvidenceParseError
from app.evidence.models import EvidenceTier, Jurisdiction
from app.evidence.pubmed import default_rate_per_sec, efetch, esearch
from app.evidence.throttle import TokenBucketRateLimiter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "evidence"


class FakeResponse:
    def __init__(
        self, status_code: int, *, json_payload: dict[str, Any] | None = None, text: str = ""
    ) -> None:
        self.status_code = status_code
        self._json_payload = json_payload
        self._text = text

    def json(self) -> dict[str, Any]:
        assert self._json_payload is not None
        return self._json_payload

    @property
    def text(self) -> str:
        return self._text


def test_esearch_parses_idlist() -> None:
    payload = json.loads((FIXTURES_DIR / "pubmed_esearch.json").read_text(encoding="utf-8"))
    response = FakeResponse(200, json_payload=payload)
    calls: list[str] = []

    def http_get(url: str) -> FakeResponse:
        calls.append(url)
        return response

    idlist = esearch("hyperkalemia AND treatment", http_get=http_get, retmax=10)

    assert idlist == ["12345678", "23456789"]
    assert len(calls) == 1
    assert "db=pubmed" in calls[0]
    assert "retmode=json" in calls[0]


def test_esearch_charges_throttle_and_budget() -> None:
    payload = json.loads((FIXTURES_DIR / "pubmed_esearch.json").read_text(encoding="utf-8"))
    response = FakeResponse(200, json_payload=payload)

    def http_get(url: str) -> FakeResponse:
        return response

    throttle = TokenBucketRateLimiter(
        rate_per_sec=1000.0, monotonic=lambda: 0.0, sleep=lambda s: None
    )
    budget = CallBudget({"pubmed": 5})

    esearch("term", http_get=http_get, retmax=5, throttle=throttle, budget=budget)

    assert budget.counts() == {"pubmed": 1}


def test_esearch_non_200_raises() -> None:
    response = FakeResponse(503, json_payload={})

    def http_get(url: str) -> FakeResponse:
        return response

    with pytest.raises(EvidenceParseError):
        esearch("term", http_get=http_get, retmax=5)


def test_esearch_malformed_response_raises() -> None:
    response = FakeResponse(200, json_payload={"unexpected": "shape"})

    def http_get(url: str) -> FakeResponse:
        return response

    with pytest.raises(EvidenceParseError):
        esearch("term", http_get=http_get, retmax=5)


def test_efetch_parses_verbatim_abstract_and_metadata() -> None:
    xml_text = (FIXTURES_DIR / "pubmed_efetch.xml").read_text(encoding="utf-8")
    response = FakeResponse(200, text=xml_text)
    calls: list[str] = []

    def http_get(url: str) -> FakeResponse:
        calls.append(url)
        return response

    retrieved_at = datetime(2026, 8, 20, tzinfo=UTC)
    records = efetch(["12345678", "23456789"], http_get=http_get, retrieved_at=retrieved_at)

    assert len(calls) == 1
    assert "id=12345678%2C23456789" in calls[0] or "id=12345678,23456789" in calls[0]
    assert len(records) == 2

    first = records[0]
    assert first.id == "pubmed:12345678"
    assert first.tier == EvidenceTier.LITERATURE
    assert first.jurisdiction == Jurisdiction.NOT_APPLICABLE
    assert first.source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert "Hyperkalemia is a common complication" in first.content
    assert "Newer potassium binders" in first.content
    assert first.metadata["doi"] == "10.1000/example.2022.001"
    assert "Review" in first.metadata["publication_types"]
    assert "Hyperkalemia" in first.metadata["mesh"]
    assert first.content_hash
    assert first.retrieved_at == retrieved_at

    second = records[1]
    assert second.id == "pubmed:23456789"
    assert second.metadata["doi"] == ""
    assert second.publication_date == "2021 Jan-Feb"


def test_efetch_empty_pmids_returns_empty_without_calling_http() -> None:
    def http_get(url: str) -> FakeResponse:
        raise AssertionError("http_get must not be called for an empty pmid list")

    result = efetch([], http_get=http_get, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))
    assert result == []


def test_efetch_invalid_xml_raises() -> None:
    response = FakeResponse(200, text="<not-valid-xml")

    def http_get(url: str) -> FakeResponse:
        return response

    with pytest.raises(EvidenceParseError):
        efetch(["1"], http_get=http_get, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))


def test_default_rate_per_sec() -> None:
    assert default_rate_per_sec(None) == 3.0
    assert default_rate_per_sec("some-key") == 10.0
