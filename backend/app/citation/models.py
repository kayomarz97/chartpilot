"""Result types for deterministic citation checking (spec Gates 1-4).

`CitationResult.computed_start_offset`/`computed_end_offset` are always
offsets into the NORMALIZED source text (`app.citation.normalization.
normalize_text` applied to the cited `EvidenceRecord.content`), never the
raw text -- normalization can change string length (collapsing whitespace,
folding ligatures, ...), so a raw-text offset would not survive it. Callers
that need to highlight the raw source must re-derive the location
themselves; this layer only guarantees the offsets are correct against the
normalized text, which is exactly what was compared.

`artifact_content_hash` pins the result to the exact evidence content the
offsets were computed against (spec §19) -- see
`app.citation.verifier.offsets_still_valid`, which uses it to detect a
refreshed/changed artifact and force re-verification rather than silently
reusing stale offsets.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CitationVerdict(StrEnum):
    """The outcome of running a single citation through Gates 1-4."""

    VERIFIED_SPAN = "verified_span"
    REJECT = "reject"
    FLAG_FOR_REVIEW = "flag_for_review"


class GateName(StrEnum):
    """One of the four deterministic citation-checking gates."""

    SOURCE_RETRIEVAL = "source_retrieval"
    CONTENT_HASH = "content_hash"
    SPAN_VERIFICATION = "span_verification"
    METADATA = "metadata"


class GateResult(BaseModel):
    """The outcome of one gate evaluated for one citation."""

    model_config = ConfigDict(frozen=True)

    gate: GateName
    passed: bool
    detail: str


class CitationResult(BaseModel):
    """The full outcome of verifying one `ExternalEvidenceRef` (spec §17,
    §19). See module docstring for the normalized-offset and
    artifact-hash-pinning contract."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    snapshot_id: str | None
    verdict: CitationVerdict
    gates: tuple[GateResult, ...]
    raw_span: str
    normalized_span: str
    computed_start_offset: int | None
    computed_end_offset: int | None
    artifact_content_hash: str | None
