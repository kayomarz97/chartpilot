"""Tests for `app.evidence.snapshot`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evidence.errors import EvidenceCapExceeded, SnapshotImmutableError
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.snapshot import (
    MAX_GUIDELINE_RECORDS,
    MAX_LITERATURE_RECORDS,
    build_snapshot,
    persist_snapshot,
)

RETRIEVED_AT = datetime(2026, 8, 20, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 20, 1, 0, 0, tzinfo=UTC)


def _record(
    record_id: str, text: str, tier: EvidenceTier = EvidenceTier.LITERATURE
) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        tier=tier,
        title=f"title-{record_id}",
        publisher="Example Publisher",
        jurisdiction=Jurisdiction.NOT_APPLICABLE,
        publication_date="2024",
        version=None,
        content=text,
        content_hash=content_hash(text),
        source_url=f"https://example.invalid/{record_id}",
        retrieved_at=RETRIEVED_AT,
        metadata={},
    )


def test_snapshot_id_is_deterministic_regardless_of_order() -> None:
    r1 = _record("a", "content a")
    r2 = _record("b", "content b")

    snap_forward = build_snapshot([r1, r2], created_at=CREATED_AT)
    snap_reversed = build_snapshot([r2, r1], created_at=CREATED_AT)

    assert snap_forward.snapshot_id == snap_reversed.snapshot_id
    assert snap_forward.manifest_hash == snap_reversed.manifest_hash


def test_snapshot_id_changes_when_content_changes() -> None:
    r1 = _record("a", "content a")
    r2 = _record("a", "different content")

    snap1 = build_snapshot([r1], created_at=CREATED_AT)
    snap2 = build_snapshot([r2], created_at=CREATED_AT)

    assert snap1.snapshot_id != snap2.snapshot_id


def test_literature_cap_exceeded_raises() -> None:
    records = [_record(f"lit-{i}", f"content {i}") for i in range(MAX_LITERATURE_RECORDS + 1)]
    with pytest.raises(EvidenceCapExceeded):
        build_snapshot(records, created_at=CREATED_AT)


def test_guideline_cap_exceeded_raises() -> None:
    records = [
        _record(f"gl-{i}", f"content {i}", tier=EvidenceTier.GUIDELINE)
        for i in range(MAX_GUIDELINE_RECORDS + 1)
    ]
    with pytest.raises(EvidenceCapExceeded):
        build_snapshot(records, created_at=CREATED_AT)


def test_snapshot_get_returns_record_or_none() -> None:
    r1 = _record("a", "content a")
    snap = build_snapshot([r1], created_at=CREATED_AT)

    assert snap.get("a") is r1
    assert snap.get("missing") is None


def test_persist_then_refresh_new_snapshot_leaves_first_untouched(tmp_path: Path) -> None:
    r1 = _record("a", "content a")
    snap1 = build_snapshot([r1], created_at=CREATED_AT)
    path1 = persist_snapshot(snap1, base_dir=tmp_path)
    original_bytes = path1.read_bytes()

    r2 = _record("b", "content b")
    snap2 = build_snapshot([r1, r2], created_at=CREATED_AT)
    path2 = persist_snapshot(snap2, base_dir=tmp_path)

    assert snap1.snapshot_id != snap2.snapshot_id
    assert path1 != path2
    assert path1.read_bytes() == original_bytes


def test_persist_identical_content_is_no_op(tmp_path: Path) -> None:
    r1 = _record("a", "content a")
    snap = build_snapshot([r1], created_at=CREATED_AT)

    path_first = persist_snapshot(snap, base_dir=tmp_path)
    mtime_first = path_first.stat().st_mtime_ns
    path_second = persist_snapshot(snap, base_dir=tmp_path)

    assert path_first == path_second
    assert path_second.stat().st_mtime_ns == mtime_first


def test_persist_different_content_to_same_path_raises(tmp_path: Path) -> None:
    r1 = _record("a", "content a")
    snap = build_snapshot([r1], created_at=CREATED_AT)
    persist_snapshot(snap, base_dir=tmp_path)

    # Same snapshot_id directory but corrupt the manifest on disk so it now
    # disagrees with what `snap` would produce -- simulates an attempted
    # mutation of an existing snapshot.
    manifest_path = tmp_path / snap.snapshot_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0]["content_hash"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SnapshotImmutableError):
        persist_snapshot(snap, base_dir=tmp_path)


def test_persist_writes_record_files(tmp_path: Path) -> None:
    r1 = _record("a", "content a")
    snap = build_snapshot([r1], created_at=CREATED_AT)
    manifest_path = persist_snapshot(snap, base_dir=tmp_path)

    records_dir = manifest_path.parent / "records"
    written = list(records_dir.glob("*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["id"] == "a"
    assert payload["content"] == "content a"
