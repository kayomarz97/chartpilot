"""Build and persist immutable evidence snapshots (spec §19, §12A.6).

A snapshot is a capped, hashed, write-once bundle of `EvidenceRecord`s.
`build_snapshot` enforces the per-tier record caps; `persist_snapshot`
writes it to disk such that an existing snapshot directory is NEVER
mutated -- a changed set of records always produces a new `snapshot_id`
(and therefore a new directory), leaving every prior snapshot byte-
identical.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.evidence.errors import EvidenceCapExceeded, SnapshotImmutableError
from app.evidence.hashing import content_hash
from app.evidence.hashing import snapshot_id as compute_snapshot_id
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier

#: Per-tier caps a snapshot may never exceed (spec §19 / §12A.6).
MAX_LITERATURE_RECORDS = 150
MAX_GUIDELINE_RECORDS = 15


def build_snapshot(records: list[EvidenceRecord], *, created_at: datetime) -> EvidenceSnapshot:
    """Build an immutable `EvidenceSnapshot` from `records`.

    Raises `EvidenceCapExceeded` if LITERATURE records exceed
    `MAX_LITERATURE_RECORDS` or GUIDELINE records exceed
    `MAX_GUIDELINE_RECORDS`.
    """
    literature_count = sum(1 for r in records if r.tier == EvidenceTier.LITERATURE)
    guideline_count = sum(1 for r in records if r.tier == EvidenceTier.GUIDELINE)

    if literature_count > MAX_LITERATURE_RECORDS:
        raise EvidenceCapExceeded(
            f"snapshot has {literature_count} LITERATURE records, "
            f"exceeds cap of {MAX_LITERATURE_RECORDS}"
        )
    if guideline_count > MAX_GUIDELINE_RECORDS:
        raise EvidenceCapExceeded(
            f"snapshot has {guideline_count} GUIDELINE records, "
            f"exceeds cap of {MAX_GUIDELINE_RECORDS}"
        )

    records_tuple = tuple(records)
    sid = compute_snapshot_id(records_tuple)
    manifest_hash = _manifest_hash(records_tuple, sid)

    return EvidenceSnapshot(
        snapshot_id=sid,
        created_at=created_at,
        records=records_tuple,
        manifest_hash=manifest_hash,
    )


def _record_summary(record: EvidenceRecord) -> dict[str, str]:
    return {"id": record.id, "content_hash": record.content_hash, "tier": record.tier.value}


def _manifest_hash(records: tuple[EvidenceRecord, ...], sid: str) -> str:
    canonical = json.dumps(
        {
            "snapshot_id": sid,
            "records": sorted((_record_summary(r) for r in records), key=lambda d: d["id"]),
        },
        sort_keys=True,
    )
    return content_hash(canonical)


def _manifest_payload(snapshot: EvidenceSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at.isoformat(),
        "manifest_hash": snapshot.manifest_hash,
        "records": sorted((_record_summary(r) for r in snapshot.records), key=lambda d: d["id"]),
    }


def _safe_filename(record_id: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in record_id)


def persist_snapshot(snapshot: EvidenceSnapshot, *, base_dir: Path) -> Path:
    """Write `snapshot` to `base_dir/<snapshot_id>/manifest.json` (+records).

    - If the target directory doesn't exist yet, it is created and written.
    - If it exists with IDENTICAL manifest content, this is a no-op.
    - If it exists with DIFFERENT content, raises `SnapshotImmutableError` --
      an existing snapshot is never mutated in place.

    Returns the path to `manifest.json`.
    """
    target_dir = base_dir / snapshot.snapshot_id
    manifest_path = target_dir / "manifest.json"
    manifest_payload = _manifest_payload(snapshot)

    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest_payload:
            raise SnapshotImmutableError(
                f"snapshot {snapshot.snapshot_id} already exists with different "
                f"content at {target_dir}"
            )
        return manifest_path

    records_dir = target_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    for record in snapshot.records:
        record_path = records_dir / f"{_safe_filename(record.id)}.json"
        payload = json.loads(record.model_dump_json())
        record_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path
