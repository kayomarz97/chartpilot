"""PubMed E-utilities adapter (spec §12A).

Two calls: `esearch` (finds PMIDs matching a term) and `efetch` (fetches the
full XML records for a list of PMIDs and parses them into
`EvidenceRecord`s). The `AbstractText` extracted by `efetch` is stored
VERBATIM as `content` -- this is the exact text later used for citation
span-matching.

Both HTTP calls are injected (`http_get`), mirroring
`app.fhir.transport.HttpFhirTransport`: this module never performs real
network I/O itself.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

from app.evidence.budget import CallBudget
from app.evidence.errors import EvidenceParseError
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.throttle import TokenBucketRateLimiter

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

#: NCBI's documented conservative rate without an API key. With a key, NCBI
#: permits 10/s -- callers should build their throttle at `default_rate_
#: per_sec(api_key)` rather than hard-coding either number themselves.
DEFAULT_RATE_NO_KEY = 3.0
DEFAULT_RATE_WITH_KEY = 10.0


def default_rate_per_sec(api_key: str | None = None) -> float:
    """Return the NCBI-documented safe request rate for the given auth."""
    return DEFAULT_RATE_WITH_KEY if api_key else DEFAULT_RATE_NO_KEY


@runtime_checkable
class HttpResponse(Protocol):
    """The minimal shape this adapter needs from an HTTP response."""

    status_code: int

    def json(self) -> dict[str, Any]:
        """Parse and return the response body as JSON (used by esearch)."""
        ...

    @property
    def text(self) -> str:
        """The raw response body as text (used by efetch, which is XML)."""
        ...


def _build_params(
    *,
    tool: str,
    email: str | None,
    api_key: str | None,
    extra: dict[str, str],
) -> dict[str, str]:
    params: dict[str, str] = {"tool": tool, **extra}
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    return params


def esearch(
    term: str,
    *,
    http_get: Callable[[str], HttpResponse],
    retmax: int,
    api_key: str | None = None,
    tool: str = "chartpilot",
    email: str | None = None,
    throttle: TokenBucketRateLimiter | None = None,
    budget: CallBudget | None = None,
) -> list[str]:
    """Search PubMed for `term`, returning up to `retmax` matching PMIDs."""
    if budget is not None:
        budget.charge("pubmed")
    if throttle is not None:
        throttle.acquire()

    params = _build_params(
        tool=tool,
        email=email,
        api_key=api_key,
        extra={"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax)},
    )
    url = f"{_ESEARCH_URL}?{urlencode(params)}"

    response = http_get(url)
    if response.status_code != 200:
        raise EvidenceParseError(
            f"PubMed esearch failed for {term!r}: status {response.status_code}"
        )

    payload = response.json()
    try:
        idlist = payload["esearchresult"]["idlist"]
    except (KeyError, TypeError) as exc:
        raise EvidenceParseError(f"malformed PubMed esearch response: {exc}") from exc
    if not isinstance(idlist, list):
        raise EvidenceParseError("malformed PubMed esearch response: idlist is not a list")
    return [str(pmid) for pmid in idlist]


def efetch(
    pmids: list[str],
    *,
    http_get: Callable[[str], HttpResponse],
    retrieved_at: datetime,
    api_key: str | None = None,
    tool: str = "chartpilot",
    email: str | None = None,
    throttle: TokenBucketRateLimiter | None = None,
    budget: CallBudget | None = None,
) -> list[EvidenceRecord]:
    """Fetch and parse the full records for `pmids` into `EvidenceRecord`s."""
    if not pmids:
        return []

    if budget is not None:
        budget.charge("pubmed")
    if throttle is not None:
        throttle.acquire()

    params = _build_params(
        tool=tool,
        email=email,
        api_key=api_key,
        extra={"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml"},
    )
    url = f"{_EFETCH_URL}?{urlencode(params)}"

    response = http_get(url)
    if response.status_code != 200:
        raise EvidenceParseError(f"PubMed efetch failed: status {response.status_code}")

    return _parse_efetch_xml(response.text, retrieved_at=retrieved_at)


def _text_of(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_efetch_xml(xml_text: str, *, retrieved_at: datetime) -> list[EvidenceRecord]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise EvidenceParseError(f"invalid PubMed efetch XML: {exc}") from exc

    records: list[EvidenceRecord] = []
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        if pmid_el is None or not pmid_el.text:
            raise EvidenceParseError("PubMed article missing a PMID")
        pmid = pmid_el.text.strip()

        title = _text_of(article.find(".//ArticleTitle"))

        abstract_parts = [_text_of(el) for el in article.findall(".//Abstract/AbstractText")]
        abstract = "\n\n".join(part for part in abstract_parts if part)

        journal = _text_of(article.find(".//Journal/Title"))

        pub_date = _text_of(article.find(".//JournalIssue/PubDate/Year")) or None
        if pub_date is None:
            pub_date = _text_of(article.find(".//JournalIssue/PubDate/MedlineDate")) or None

        publication_types = [
            _text_of(pt)
            for pt in article.findall(".//PublicationTypeList/PublicationType")
            if _text_of(pt)
        ]

        mesh_terms = [
            _text_of(mh)
            for mh in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
            if _text_of(mh)
        ]

        doi = ""
        for eloc in article.findall(".//ELocationID"):
            if eloc.get("EIdType") == "doi" and eloc.text:
                doi = eloc.text.strip()
                break

        records.append(
            EvidenceRecord(
                id=f"pubmed:{pmid}",
                tier=EvidenceTier.LITERATURE,
                title=title,
                publisher=journal,
                jurisdiction=Jurisdiction.NOT_APPLICABLE,
                publication_date=pub_date,
                version=None,
                content=abstract,
                content_hash=content_hash(abstract),
                source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                retrieved_at=retrieved_at,
                metadata={
                    "publication_types": ",".join(publication_types),
                    "mesh": ",".join(mesh_terms),
                    "doi": doi,
                },
            )
        )
    return records
