"""Content and snapshot hashing.

`content_hash` fixes the exact bytes of a citable text so any later
tampering or accidental re-encoding is detectable. `snapshot_id` fixes the
identity of a *set* of records regardless of the order they were retrieved
or listed in -- reproducibility (spec §19) depends on this being order-
independent and depending on nothing but `(id, content_hash)` pairs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.evidence.models import EvidenceRecord


def content_hash(text: str) -> str:
    """Return the sha256 hex digest of `text` (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_id(records: Iterable[EvidenceRecord]) -> str:
    """Deterministic snapshot id for a set of records.

    Computed as the sha256 hex digest of the SORTED list of
    `(record.id, record.content_hash)` pairs, truncated to the first 16 hex
    characters. Sorting first means the same set of records always yields
    the same id regardless of input order.
    """
    pairs = sorted((record.id, record.content_hash) for record in records)
    joined = "\n".join(f"{record_id}:{chash}" for record_id, chash in pairs)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return digest[:16]
