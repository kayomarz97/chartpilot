"""Tests for `app.evidence.guideline_citations`.

`http_get` is an injected stub reading the SAME recorded PubMed fixtures
`test_pubmed.py` uses -- these tests never touch the network. The point of
this module is the re-tiering behavior (LITERATURE -> GUIDELINE,
`reviewed_by=PENDING`) and the query-term filter, not re-testing PubMed XML
parsing itself (already covered by `test_pubmed.py`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.evidence.errors import EvidenceParseError
from app.evidence.guideline_citations import (
    GUIDELINE_PUBLICATION_TYPE_TERM,
    build_guideline_query,
    fetch_guideline_citations,
    search_and_fetch_guideline_citations,
    search_guideline_citations,
)
from app.evidence.guideline_pack import is_clinician_reviewed
from app.evidence.models import EvidenceTier, Jurisdiction

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


def test_build_guideline_query_appends_publication_type_filter() -> None:
    query = build_guideline_query("hyperkalemia AND treatment")
    assert query == 'hyperkalemia AND treatment AND "guideline"[Publication Type]'
    assert GUIDELINE_PUBLICATION_TYPE_TERM in query


def test_search_guideline_citations_sends_filtered_term() -> None:
    payload = json.loads((FIXTURES_DIR / "pubmed_esearch.json").read_text(encoding="utf-8"))
    response = FakeResponse(200, json_payload=payload)
    calls: list[str] = []

    def http_get(url: str) -> FakeResponse:
        calls.append(url)
        return response

    idlist = search_guideline_citations("hyperkalemia", http_get=http_get, retmax=10)

    assert idlist == ["12345678", "23456789"]
    assert len(calls) == 1
    sent_term = parse_qs(urlparse(calls[0]).query)["term"][0]
    assert sent_term == 'hyperkalemia AND "guideline"[Publication Type]'


def test_fetch_guideline_citations_returns_guideline_tier_pending_review() -> None:
    xml_text = (FIXTURES_DIR / "pubmed_efetch.xml").read_text(encoding="utf-8")
    response = FakeResponse(200, text=xml_text)

    def http_get(url: str) -> FakeResponse:
        return response

    retrieved_at = datetime(2026, 8, 22, tzinfo=UTC)
    records = fetch_guideline_citations(
        ["12345678", "23456789"], http_get=http_get, retrieved_at=retrieved_at
    )

    assert len(records) == 2
    first = records[0]

    # GUIDELINE tier, not LITERATURE -- this is the whole point of the
    # re-tiering: PubMed citations to guideline publications surface as
    # guideline-tier evidence, distinct from ordinary literature abstracts.
    assert first.tier == EvidenceTier.GUIDELINE
    assert first.jurisdiction == Jurisdiction.NOT_APPLICABLE

    # A real, dereferenceable citation URL -- never a placeholder.
    assert first.source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert first.id == "pubmed_guideline:12345678"

    # The literature-derived abstract is carried over VERBATIM (never copied
    # licensed guideline body text) -- same content, same hash as plain
    # `pubmed.efetch` would have parsed.
    assert "Hyperkalemia is a common complication" in first.content
    assert first.content_hash

    # Never clinician-reviewed by construction.
    assert first.metadata["reviewed_by"] == "PENDING"
    assert is_clinician_reviewed(first) is False

    # Citation metadata (doi/publication_types/mesh) from efetch is preserved.
    assert first.metadata["doi"] == "10.1000/example.2022.001"
    assert "Review" in first.metadata["publication_types"]


def test_fetch_guideline_citations_empty_pmids_returns_empty_without_calling_http() -> None:
    def http_get(url: str) -> FakeResponse:
        raise AssertionError("http_get must not be called for an empty pmid list")

    result = fetch_guideline_citations(
        [], http_get=http_get, retrieved_at=datetime(2026, 8, 22, tzinfo=UTC)
    )
    assert result == []


def test_search_and_fetch_guideline_citations_end_to_end_hermetic() -> None:
    esearch_payload = json.loads((FIXTURES_DIR / "pubmed_esearch.json").read_text(encoding="utf-8"))
    efetch_xml = (FIXTURES_DIR / "pubmed_efetch.xml").read_text(encoding="utf-8")
    calls: list[str] = []

    def http_get(url: str) -> FakeResponse:
        calls.append(url)
        if "esearch.fcgi" in url:
            return FakeResponse(200, json_payload=esearch_payload)
        return FakeResponse(200, text=efetch_xml)

    records = search_and_fetch_guideline_citations(
        "hyperkalemia AND treatment",
        http_get=http_get,
        retmax=10,
        retrieved_at=datetime(2026, 8, 22, tzinfo=UTC),
    )

    assert len(calls) == 2
    assert len(records) == 2
    assert all(r.tier == EvidenceTier.GUIDELINE for r in records)
    assert all(r.metadata["reviewed_by"] == "PENDING" for r in records)
    assert all(not is_clinician_reviewed(r) for r in records)


def test_fetch_guideline_citations_non_200_raises() -> None:
    response = FakeResponse(503, text="")

    def http_get(url: str) -> FakeResponse:
        return response

    with pytest.raises(EvidenceParseError):
        fetch_guideline_citations(
            ["1"], http_get=http_get, retrieved_at=datetime(2026, 8, 22, tzinfo=UTC)
        )
