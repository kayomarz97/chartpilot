"""Evidence models: the trustworthy, hashable, citable shapes this layer
produces.

An `EvidenceRecord` is one citable unit -- a label section, a verbatim
abstract, or a curated guideline excerpt. `content` is always the EXACT text
later used for citation span-matching; nothing downstream may cite text that
isn't byte-identical to what is stored here. An `EvidenceSnapshot` is an
immutable, reproducibly-hashed bundle of records (spec §19).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class EvidenceTier(StrEnum):
    """The kind of evidence a record represents."""

    REGULATORY_LABEL = "regulatory_label"
    LITERATURE = "literature"
    GUIDELINE = "guideline"


class Jurisdiction(StrEnum):
    """The regulatory jurisdiction a record's authority is scoped to."""

    US_FDA = "us_fda"
    NOT_APPLICABLE = "not_applicable"


def _reject_naive_datetime(v: datetime) -> datetime:
    """Fail closed: no naive datetime may ever exist in this model.

    Mirrors `app.normalize.temporal.ClinicalInstant._reject_naive`.
    """
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("datetime must be tz-aware, got a naive datetime")
    return v.astimezone(UTC)


class EvidenceRecord(BaseModel):
    """One citable piece of evidence, retrieved from a single source.

    `metadata` is tier-specific (e.g. set_id/effective_time/application_number
    for REGULATORY_LABEL; publication_types/mesh/doi for LITERATURE;
    reviewed_by for GUIDELINE) -- deliberately a loose `dict[str, str]`
    rather than a union of tier-specific models, since Phase 6 has no need
    to branch on it structurally, only to read it.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tier: EvidenceTier
    title: str
    publisher: str
    jurisdiction: Jurisdiction
    publication_date: str | None
    version: str | None
    content: str
    content_hash: str
    source_url: str
    retrieved_at: datetime
    metadata: dict[str, str]

    @field_validator("retrieved_at")
    @classmethod
    def _validate_retrieved_at(cls, v: datetime) -> datetime:
        return _reject_naive_datetime(v)


class EvidenceSnapshot(BaseModel):
    """An immutable, reproducibly-identified bundle of evidence records.

    `snapshot_id` is deterministic in the records alone (see
    `app.evidence.hashing.snapshot_id`): the same set of records always
    produces the same id, which is what makes a persisted snapshot directory
    safe to treat as immutable (spec §19).
    """

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    created_at: datetime
    records: tuple[EvidenceRecord, ...]
    manifest_hash: str

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, v: datetime) -> datetime:
        return _reject_naive_datetime(v)

    def get(self, record_id: str) -> EvidenceRecord | None:
        """Return the record with `record_id`, or None if not present."""
        for record in self.records:
            if record.id == record_id:
                return record
        return None
