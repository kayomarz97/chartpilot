"""Loader for the curated guideline pack (spec §12).

The pack is intentionally narrow and human-reviewed: every file in
`evidence/guideline-pack/*.json` becomes one GUIDELINE `EvidenceRecord`, and
every one of those files must be explicit about whether a clinician has
actually reviewed it (`reviewed_by`). This module NEVER writes a reviewer
name -- sample/placeholder records ship with `"reviewed_by": "PENDING"`, and
`is_clinician_reviewed` reports them as unreviewed until a human edits that
field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.evidence.errors import EvidenceCapExceeded, EvidenceParseError
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction

#: The §12 cap on curated guideline records.
MAX_GUIDELINE_RECORDS = 15

_PENDING_MARKERS = {"PENDING", ""}

_REQUIRED_FIELDS = (
    "publisher",
    "title",
    "url",
    "publication_date",
    "version",
    "excerpt",
    "section",
    "license_status",
    "jurisdiction",
    "claim_type",
    "reviewed_by",
)


def is_clinician_reviewed(record: EvidenceRecord) -> bool:
    """True iff `record.metadata["reviewed_by"]` names an actual reviewer.

    False for a missing key, an empty string, or the literal placeholder
    `"PENDING"` -- all of these mean "not yet reviewed."
    """
    reviewed_by = record.metadata.get("reviewed_by", "")
    return reviewed_by not in _PENDING_MARKERS


def load_guideline_pack(
    pack_dir: Path, *, retrieved_at: datetime | None = None
) -> list[EvidenceRecord]:
    """Load every `*.json` file in `pack_dir` as a GUIDELINE `EvidenceRecord`.

    Raises `EvidenceCapExceeded` if the pack holds more than
    `MAX_GUIDELINE_RECORDS` files -- this cap exists to keep the pack small
    enough that every entry can plausibly be clinician-reviewed (spec §12).
    """
    paths = sorted(pack_dir.glob("*.json"))
    if len(paths) > MAX_GUIDELINE_RECORDS:
        raise EvidenceCapExceeded(
            f"guideline pack at {pack_dir} has {len(paths)} files, "
            f"exceeds cap of {MAX_GUIDELINE_RECORDS}"
        )

    loaded_at = retrieved_at if retrieved_at is not None else datetime.now(UTC)
    return [_load_one(path, retrieved_at=loaded_at) for path in paths]


def _load_one(path: Path, *, retrieved_at: datetime) -> EvidenceRecord:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceParseError(f"failed to load guideline pack file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise EvidenceParseError(f"guideline pack file {path} is not a JSON object")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise EvidenceParseError(f"guideline pack file {path} missing fields: {missing}")

    jurisdiction_raw = str(raw["jurisdiction"])
    try:
        jurisdiction = Jurisdiction(jurisdiction_raw)
    except ValueError as exc:
        raise EvidenceParseError(
            f"guideline pack file {path} has unknown jurisdiction {jurisdiction_raw!r}"
        ) from exc

    excerpt = str(raw["excerpt"])
    publication_date = raw.get("publication_date")
    version = raw.get("version")

    return EvidenceRecord(
        id=f"guideline:{path.stem}",
        tier=EvidenceTier.GUIDELINE,
        title=str(raw["title"]),
        publisher=str(raw["publisher"]),
        jurisdiction=jurisdiction,
        publication_date=str(publication_date) if publication_date else None,
        version=str(version) if version else None,
        content=excerpt,
        content_hash=content_hash(excerpt),
        source_url=str(raw["url"]),
        retrieved_at=retrieved_at,
        metadata={
            "section": str(raw["section"]),
            "license_status": str(raw["license_status"]),
            "claim_type": str(raw["claim_type"]),
            "reviewed_by": str(raw["reviewed_by"]),
        },
    )
