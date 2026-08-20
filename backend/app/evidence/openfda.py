"""openFDA `/drug/label.json` adapter and the §14 SPL-selection policy.

openFDA can return several label documents for one ingredient (different
manufacturers, an NDA reference-listed drug alongside its ANDA generics,
re-submissions at different `effective_time`s). §14's policy exists so this
layer never silently guesses which one is authoritative -- it either finds
one clear winner or raises `LabelSelectionAmbiguous` as a review flag.

The HTTP call is injected (`http_get`), mirroring
`app.fhir.transport.HttpFhirTransport`: this module never performs real
network I/O itself.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from app.evidence.budget import CallBudget
from app.evidence.errors import EvidenceParseError, LabelSelectionAmbiguous
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.throttle import TokenBucketRateLimiter

_LABEL_URL = "https://api.fda.gov/drug/label.json"


@runtime_checkable
class HttpResponse(Protocol):
    """The minimal shape `fetch_label` needs from an HTTP response."""

    status_code: int

    def json(self) -> dict[str, Any]:
        """Parse and return the response body as JSON."""
        ...


def _matches_ingredient(result: dict[str, Any], ingredient: str) -> bool:
    """True iff `result`'s openfda generic/brand name matches `ingredient`
    (case-insensitive)."""
    openfda_meta = result.get("openfda", {})
    names = [str(n).lower() for n in openfda_meta.get("generic_name", [])]
    names += [str(n).lower() for n in openfda_meta.get("brand_name", [])]
    return ingredient.lower() in names


def _is_nda(result: dict[str, Any]) -> bool:
    application_numbers = result.get("openfda", {}).get("application_number", [])
    return any(str(a).upper().startswith("NDA") for a in application_numbers)


def _effective_time(result: dict[str, Any]) -> str:
    return str(result.get("effective_time", ""))


def select_label(results: list[dict[str, Any]], *, ingredient: str) -> dict[str, Any]:
    """Apply the §14 SPL-selection policy and return the winning label.

    Policy:
      1. Filter to candidates whose openfda generic/brand name matches
         `ingredient` (case-insensitive). Zero matches -> ambiguous.
      2. Prefer candidates with an application_number starting "NDA"
         (reference-listed) over "ANDA"/other.
      3. Within the preferred group, pick the single candidate with the
         latest `effective_time`.
      4. If step 3 does not produce exactly one winner (e.g. multiple NDAs
         tie on `effective_time`) -> raise `LabelSelectionAmbiguous`. This is
         a review flag; this function never picks arbitrarily.
    """
    matched = [r for r in results if _matches_ingredient(r, ingredient)]
    if not matched:
        raise LabelSelectionAmbiguous(f"no label results matched ingredient {ingredient!r}")

    preferred = [r for r in matched if _is_nda(r)]
    group = preferred if preferred else matched

    max_time = max((_effective_time(r) for r in group), default="")
    winners = [r for r in group if _effective_time(r) == max_time]

    if len(winners) != 1:
        raise LabelSelectionAmbiguous(
            f"ambiguous label selection for ingredient {ingredient!r}: "
            f"{len(winners)} candidates tie at effective_time={max_time!r}"
        )
    return winners[0]


def label_to_record(
    chosen: dict[str, Any],
    *,
    ingredient: str,
    section: str,
    retrieved_at: datetime,
) -> EvidenceRecord:
    """Build a REGULATORY_LABEL `EvidenceRecord` from a selected label.

    `content` is the joined text of `chosen[section]` (e.g.
    "contraindications") -- the exact text later used for citation
    span-matching.
    """
    openfda_meta = chosen.get("openfda", {})
    set_id = str(chosen.get("set_id", ""))
    version = str(chosen["version"]) if chosen.get("version") is not None else None
    effective_time = _effective_time(chosen)
    application_numbers = openfda_meta.get("application_number", [])
    application_number = str(application_numbers[0]) if application_numbers else ""

    section_value = chosen.get(section)
    if section_value is None:
        raise EvidenceParseError(f"label {set_id!r} has no section {section!r}")
    if isinstance(section_value, list):
        content = "\n\n".join(str(part) for part in section_value)
    else:
        content = str(section_value)

    generic_names = openfda_meta.get("generic_name", [])
    brand_names = openfda_meta.get("brand_name", [])
    title_name = (
        str(generic_names[0])
        if generic_names
        else (str(brand_names[0]) if brand_names else ingredient)
    )
    title = f"{title_name} — {section.replace('_', ' ')}"

    source_url = (
        f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
        if set_id
        else _LABEL_URL
    )

    return EvidenceRecord(
        id=f"openfda:{set_id}:{section}",
        tier=EvidenceTier.REGULATORY_LABEL,
        title=title,
        publisher="U.S. Food and Drug Administration (openFDA)",
        jurisdiction=Jurisdiction.US_FDA,
        publication_date=effective_time or None,
        version=version,
        content=content,
        content_hash=content_hash(content),
        source_url=source_url,
        retrieved_at=retrieved_at,
        metadata={
            "set_id": set_id,
            "effective_time": effective_time,
            "application_number": application_number,
            "section": section,
        },
    )


def fetch_label(
    ingredient: str,
    *,
    http_get: Callable[[str], HttpResponse],
    section: str,
    retrieved_at: datetime,
    throttle: TokenBucketRateLimiter | None = None,
    budget: CallBudget | None = None,
) -> EvidenceRecord:
    """Fetch, select, and build a label `EvidenceRecord` for `ingredient`.

    `http_get` is the only I/O boundary -- callers inject a real or fake
    implementation, so this function never touches the network itself.
    """
    if budget is not None:
        budget.charge("openfda")
    if throttle is not None:
        throttle.acquire()

    query = quote(f'openfda.generic_name:"{ingredient}"')
    url = f"{_LABEL_URL}?search={query}&limit=100"

    response = http_get(url)
    if response.status_code != 200:
        raise EvidenceParseError(
            f"openFDA label fetch failed for {ingredient!r}: status {response.status_code}"
        )

    payload = response.json()
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise EvidenceParseError("malformed openFDA response: 'results' is not a list")

    chosen = select_label(results, ingredient=ingredient)
    return label_to_record(
        chosen, ingredient=ingredient, section=section, retrieved_at=retrieved_at
    )
