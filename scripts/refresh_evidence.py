#!/usr/bin/env python3
"""Manually refresh the evidence snapshot from live sources.

This is a MANUAL, human-triggered script -- it is deliberately NOT part of
`make check` (see the `refresh-evidence` Makefile target, which is separate
from `check`). It is the only place in this codebase allowed to perform real
network I/O against openFDA / PubMed; every tested code path in
`app.evidence` takes an injected `http_get` and is exercised against
recorded fixtures instead.

Usage:
    cd backend && uv run python ../scripts/refresh_evidence.py
    # or, from the repo root:
    make refresh-evidence

Writes a new snapshot directory under `evidence/snapshots/<snapshot_id>/`
(gitignored -- see .gitignore). Never overwrites an existing snapshot
directory with different content; a changed set of records always produces
a new snapshot_id (spec §19).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# Make `app.evidence.*` importable regardless of the caller's cwd -- this
# script can be invoked from the repo root or from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "evidence" / "snapshots"
GUIDELINE_PACK_DIR = REPO_ROOT / "evidence" / "guideline-pack"

# A small, illustrative set of ingredients/terms to refresh. Expand this
# list deliberately, one reviewed addition at a time -- it directly drives
# how many external calls this script makes per run.
INGREDIENTS = ["warfarin sodium", "spironolactone"]
LABEL_SECTIONS = ["contraindications", "warnings"]
PUBMED_TERMS = ["hyperkalemia AND treatment"]
PUBMED_RETMAX = 5


def _build_http_get() -> object:
    """Build a real httpx-backed `http_get` callable.

    Imported lazily, and only from this manual script -- no tested code
    path in `app.evidence` needs `httpx` at runtime.
    """
    import httpx

    client = httpx.Client(timeout=30.0)

    def http_get(url: str) -> httpx.Response:
        return client.get(url)

    return http_get


def main() -> None:
    from app.evidence.budget import CallBudget
    from app.evidence.errors import EvidenceError
    from app.evidence.guideline_pack import load_guideline_pack
    from app.evidence.openfda import fetch_label
    from app.evidence.pubmed import default_rate_per_sec, efetch, esearch
    from app.evidence.snapshot import build_snapshot, persist_snapshot
    from app.evidence.throttle import TokenBucketRateLimiter

    http_get = _build_http_get()
    retrieved_at = datetime.now(UTC)

    openfda_throttle = TokenBucketRateLimiter(rate_per_sec=2.0)
    pubmed_throttle = TokenBucketRateLimiter(rate_per_sec=default_rate_per_sec(api_key=None))
    budget = CallBudget({"openfda": 20, "pubmed": 20})

    records = []

    for ingredient in INGREDIENTS:
        for section in LABEL_SECTIONS:
            try:
                record = fetch_label(
                    ingredient,
                    http_get=http_get,  # type: ignore[arg-type]
                    section=section,
                    retrieved_at=retrieved_at,
                    throttle=openfda_throttle,
                    budget=budget,
                )
            except EvidenceError as exc:
                print(f"[skip] openFDA {ingredient!r}/{section!r}: {exc}")
                continue
            records.append(record)
            print(f"[ok] openFDA {ingredient!r}/{section!r} -> {record.id}")

    for term in PUBMED_TERMS:
        try:
            pmids = esearch(
                term,
                http_get=http_get,  # type: ignore[arg-type]
                retmax=PUBMED_RETMAX,
                throttle=pubmed_throttle,
                budget=budget,
            )
            fetched = efetch(
                pmids,
                http_get=http_get,  # type: ignore[arg-type]
                retrieved_at=retrieved_at,
                throttle=pubmed_throttle,
                budget=budget,
            )
        except EvidenceError as exc:
            print(f"[skip] PubMed {term!r}: {exc}")
            continue
        records.extend(fetched)
        print(f"[ok] PubMed {term!r} -> {len(fetched)} record(s)")

    records.extend(load_guideline_pack(GUIDELINE_PACK_DIR, retrieved_at=retrieved_at))

    snapshot = build_snapshot(records, created_at=retrieved_at)
    manifest_path = persist_snapshot(snapshot, base_dir=SNAPSHOTS_DIR)
    print(f"snapshot {snapshot.snapshot_id}: {len(records)} record(s) -> {manifest_path}")
    print(f"external calls made: {budget.counts()}")


if __name__ == "__main__":
    main()
