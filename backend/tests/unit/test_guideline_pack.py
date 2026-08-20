"""Tests for `app.evidence.guideline_pack`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evidence.errors import EvidenceCapExceeded, EvidenceParseError
from app.evidence.guideline_pack import (
    MAX_GUIDELINE_RECORDS,
    is_clinician_reviewed,
    load_guideline_pack,
)
from app.evidence.models import EvidenceTier

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "evidence" / "guideline-pack"


def _write_record(dir_: Path, name: str, **overrides: object) -> None:
    payload = {
        "publisher": "Example Society",
        "title": "Example Guideline",
        "url": "https://example.invalid/guideline",
        "publication_date": "2024-01-01",
        "version": "1",
        "excerpt": "Example excerpt text.",
        "section": "monitoring",
        "license_status": "public-domain",
        "jurisdiction": "not_applicable",
        "claim_type": "monitoring",
        "reviewed_by": "PENDING",
    }
    payload.update(overrides)
    (dir_ / name).write_text(json.dumps(payload), encoding="utf-8")


def test_loads_real_placeholder_pack_as_unreviewed_guideline() -> None:
    records = load_guideline_pack(PACK_DIR, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))

    assert len(records) >= 1
    placeholder = next(r for r in records if "example_placeholder" in r.id)
    assert placeholder.tier == EvidenceTier.GUIDELINE
    assert is_clinician_reviewed(placeholder) is False
    assert "PLACEHOLDER" in placeholder.content.upper()


def test_load_from_tmp_dir(tmp_path: Path) -> None:
    _write_record(tmp_path, "one.json")
    records = load_guideline_pack(tmp_path, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))

    assert len(records) == 1
    assert records[0].id == "guideline:one"
    assert records[0].tier == EvidenceTier.GUIDELINE
    assert is_clinician_reviewed(records[0]) is False


def test_is_clinician_reviewed_true_for_named_reviewer(tmp_path: Path) -> None:
    _write_record(tmp_path, "reviewed.json", reviewed_by="Dr. Jane Example, MD")
    records = load_guideline_pack(tmp_path, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))

    assert is_clinician_reviewed(records[0]) is True


def test_more_than_cap_raises(tmp_path: Path) -> None:
    for i in range(MAX_GUIDELINE_RECORDS + 1):
        _write_record(tmp_path, f"rec_{i}.json")

    with pytest.raises(EvidenceCapExceeded):
        load_guideline_pack(tmp_path, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))


def test_missing_required_field_raises(tmp_path: Path) -> None:
    payload = {"publisher": "Example"}
    (tmp_path / "bad.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvidenceParseError):
        load_guideline_pack(tmp_path, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))


def test_unknown_jurisdiction_raises(tmp_path: Path) -> None:
    _write_record(tmp_path, "bad_jurisdiction.json", jurisdiction="mars")

    with pytest.raises(EvidenceParseError):
        load_guideline_pack(tmp_path, retrieved_at=datetime(2026, 8, 20, tzinfo=UTC))
