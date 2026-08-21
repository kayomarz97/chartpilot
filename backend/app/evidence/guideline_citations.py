"""PubMed guideline-CITATION adapter (TD-012).

PubMed/E-utilities does not license clinical-guideline TEXT -- it only ever
returns citation metadata (PMID, title, journal, year, authors) and, when
the source article has one, the author's own structured abstract. This is
true even for records whose MEDLINE "Publication Type" is tagged
"Guideline"/"Practice Guideline": PubMed exposes the *citation* to a
guideline, never the guideline body itself.

This module narrows a search to that publication type, then reuses
`app.evidence.pubmed.esearch`/`efetch` verbatim for the actual network call
and XML parsing -- the only new behavior here is (a) appending the
publication-type filter to the search term, and (b) re-tiering the
resulting records as GUIDELINE (never LITERATURE) with
`metadata["reviewed_by"] = "PENDING"`, so every PubMed-sourced guideline
citation surfaces as unreviewed guideline-derived evidence.

Verified live against NCBI E-utilities on 2026-08-22:
`esearch?db=pubmed&term=<term> AND "guideline"[Publication Type]` returns
PMIDs whose `<PublicationTypeList>` includes "Practice Guideline" and/or
"Guideline" (PubMed's field-tag matching folds both MEDLINE publication-type
values under the single lowercase `"guideline"[Publication Type]` term) --
e.g. PMID 29726985 ("Expert consensus document on the management of
hyperkalaemia in patients with cardiovascular disease treated with renin
angiotensin aldosterone system inhibitors", Eur Heart J Cardiovasc
Pharmacother 2018) and PMID 33637203 (KDIGO 2021 CPG for Blood Pressure in
CKD, Kidney International) both matched this exact query shape.

`app.gate.claim_gate.finalize_claim_verdict` already caps any claim resting
on a `reviewed_by="PENDING"` GUIDELINE record at PARTIALLY_VERIFIED (spec
§12) -- this module relies on that existing gate rather than re-implementing
it, and never marks a record as reviewed itself.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.evidence.budget import CallBudget
from app.evidence.models import EvidenceRecord, EvidenceTier
from app.evidence.pubmed import HttpResponse, efetch, esearch
from app.evidence.throttle import TokenBucketRateLimiter

#: PubMed's Publication Type field-tag value that matches guideline
#: citations (folds both the "Guideline" and "Practice Guideline" MEDLINE
#: publication-type values -- see module docstring for the live-verified
#: query shape).
GUIDELINE_PUBLICATION_TYPE_TERM = '"guideline"[Publication Type]'

#: The same placeholder `guideline_pack.py` uses -- this module must never
#: write a reviewer name; every citation it produces starts unreviewed.
_REVIEWED_BY_PENDING = "PENDING"


def build_guideline_query(term: str) -> str:
    """Narrow `term` to PubMed citations tagged Publication Type "Guideline".

    Exact esearch syntax (verified live, see module docstring):
    `<term> AND "guideline"[Publication Type]`.
    """
    return f"{term} AND {GUIDELINE_PUBLICATION_TYPE_TERM}"


def search_guideline_citations(
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
    """Search PubMed for `term`, restricted to guideline-tagged citations.

    Thin wrapper over `app.evidence.pubmed.esearch` -- same throttle/budget/
    error behavior, only the query term differs (see `build_guideline_query`).
    """
    return esearch(
        build_guideline_query(term),
        http_get=http_get,
        retmax=retmax,
        api_key=api_key,
        tool=tool,
        email=email,
        throttle=throttle,
        budget=budget,
    )


def _as_guideline_citation(record: EvidenceRecord) -> EvidenceRecord:
    """Re-tier a LITERATURE record from `pubmed.efetch` as a GUIDELINE
    citation, `reviewed_by=PENDING`.

    Content and content_hash are carried over UNCHANGED: this is the exact
    same citation metadata + abstract `efetch` already parsed verbatim from
    PubMed, never rewritten and never presented as licensed guideline body
    text -- only the tier and review-state metadata change.
    """
    pmid = record.id.removeprefix("pubmed:")
    metadata = dict(record.metadata)
    metadata["reviewed_by"] = _REVIEWED_BY_PENDING
    return EvidenceRecord(
        id=f"pubmed_guideline:{pmid}",
        tier=EvidenceTier.GUIDELINE,
        title=record.title,
        publisher=record.publisher,
        jurisdiction=record.jurisdiction,
        publication_date=record.publication_date,
        version=record.version,
        content=record.content,
        content_hash=record.content_hash,
        source_url=record.source_url,
        retrieved_at=record.retrieved_at,
        metadata=metadata,
    )


def fetch_guideline_citations(
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
    """Fetch citation metadata + abstract for `pmids` as GUIDELINE records.

    Thin wrapper over `app.evidence.pubmed.efetch` (same network call, XML
    parsing, throttle/budget/error behavior) followed by `_as_guideline_
    citation` re-tiering. Every returned record has
    `tier=EvidenceTier.GUIDELINE` and `metadata["reviewed_by"] == "PENDING"`.
    """
    literature_records = efetch(
        pmids,
        http_get=http_get,
        retrieved_at=retrieved_at,
        api_key=api_key,
        tool=tool,
        email=email,
        throttle=throttle,
        budget=budget,
    )
    return [_as_guideline_citation(record) for record in literature_records]


def search_and_fetch_guideline_citations(
    term: str,
    *,
    http_get: Callable[[str], HttpResponse],
    retmax: int,
    retrieved_at: datetime,
    api_key: str | None = None,
    tool: str = "chartpilot",
    email: str | None = None,
    throttle: TokenBucketRateLimiter | None = None,
    budget: CallBudget | None = None,
) -> list[EvidenceRecord]:
    """Convenience one-shot: search then fetch, guideline-tagged, GUIDELINE-tier.

    Equivalent to calling `search_guideline_citations` then `fetch_guideline_
    citations` on its result -- provided for callers (e.g. the demo-evidence
    build scripts) that just want "citations for this term" without managing
    the intermediate PMID list themselves.
    """
    pmids = search_guideline_citations(
        term,
        http_get=http_get,
        retmax=retmax,
        api_key=api_key,
        tool=tool,
        email=email,
        throttle=throttle,
        budget=budget,
    )
    return fetch_guideline_citations(
        pmids,
        http_get=http_get,
        retrieved_at=retrieved_at,
        api_key=api_key,
        tool=tool,
        email=email,
        throttle=throttle,
        budget=budget,
    )
