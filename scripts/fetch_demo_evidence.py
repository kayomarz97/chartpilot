#!/usr/bin/env python3
"""ONE-TIME manual fetch of the Phase 14 demo evidence snapshot.

Mirrors `scripts/refresh_evidence.py`'s shape (real httpx-backed `http_get`,
never imported by tested code) but is scoped narrowly to what the Phase 14
demo needs: one openFDA label section for an ACE inhibitor (contraindications
or warnings -- whichever section actually contains potassium/hyperkalemia
language) plus one PubMed abstract about ACE-inhibitor hyperkalemia, plus the
existing guideline-pack PENDING placeholder record.

NOTE on ingredient choice: the spec asked for the `lisinopril` label, but at
fetch time openFDA's live `/drug/label.json` returned 68 lisinopril labels
tying on `effective_time` with no NDA among them -- `select_label`'s §14
policy correctly refuses to guess among ties and raises
`LabelSelectionAmbiguous`. `enalapril` (the same ACE_INHIBITOR pharmacologic
class per `app/rules/data/medication_classes.json`, and demo patients cite it
by class, not brand) has exactly one matching live label with no ambiguity,
so it is used instead. This is a real, non-fallback fetch -- not
representative demo text.

This is NOT run by `make check` / pytest -- it is a build-time script whose
output is committed as `backend/tests/fixtures/demo/evidence_snapshot.json`,
which `app.pipeline.demo_evidence.load_demo_snapshot` loads deterministically
at test time with zero network access.

Usage:
    cd backend && uv run python ../scripts/fetch_demo_evidence.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDELINE_PACK_DIR = REPO_ROOT / "evidence" / "guideline-pack"
OUTPUT_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo" / "evidence_snapshot.json"

_POTASSIUM_MARKERS = ("potassium", "hyperkalemia", "hyperkalaemia")


def _build_http_get() -> object:
    import httpx

    client = httpx.Client(timeout=30.0)

    def http_get(url: str) -> httpx.Response:
        return client.get(url)

    return http_get


def main() -> None:
    from app.evidence.errors import EvidenceError
    from app.evidence.guideline_pack import load_guideline_pack
    from app.evidence.models import EvidenceRecord
    from app.evidence.openfda import fetch_label
    from app.evidence.pubmed import default_rate_per_sec, efetch, esearch
    from app.evidence.snapshot import build_snapshot
    from app.evidence.throttle import TokenBucketRateLimiter

    http_get = _build_http_get()
    retrieved_at = datetime.now(UTC)
    fell_back: list[str] = []

    records: list[EvidenceRecord] = []

    # --- openFDA: ACE-inhibitor label, prefer a section with potassium/hyperkalemia
    # text. See module docstring for why `enalapril` is used instead of `lisinopril`.
    ingredient = "enalapril"
    label_record: EvidenceRecord | None = None
    for section in ("warnings", "precautions", "adverse_reactions", "contraindications"):
        try:
            candidate = fetch_label(
                ingredient,
                http_get=http_get,  # type: ignore[arg-type]
                section=section,
                retrieved_at=retrieved_at,
                throttle=TokenBucketRateLimiter(rate_per_sec=2.0),
            )
        except EvidenceError as exc:
            print(f"[skip] openFDA {ingredient}/{section!r}: {exc}")
            continue
        lowered = candidate.content.lower()
        if any(marker in lowered for marker in _POTASSIUM_MARKERS):
            label_record = candidate
            print(f"[ok] openFDA {ingredient}/{section!r} -> {candidate.id} (potassium language found)")
            break
        print(f"[skip] openFDA {ingredient}/{section!r} -> no potassium/hyperkalemia language")

    if label_record is None:
        fell_back.append(f"openfda:{ingredient}")
        label_record = EvidenceRecord(
            id="openfda:REPRESENTATIVE:warnings",
            tier=__import__("app.evidence.models", fromlist=["EvidenceTier"]).EvidenceTier.REGULATORY_LABEL,
            title="lisinopril — warnings (REPRESENTATIVE DEMO TEXT)",
            publisher="U.S. Food and Drug Administration (openFDA)",
            jurisdiction=__import__(
                "app.evidence.models", fromlist=["Jurisdiction"]
            ).Jurisdiction.US_FDA,
            publication_date=None,
            version=None,
            content=(
                "REPRESENTATIVE DEMO TEXT: Hyperkalemia has been reported with "
                "concomitant use of ACE inhibitors and potassium-sparing diuretics, "
                "potassium supplements, or potassium-containing salt substitutes."
            ),
            content_hash=__import__(
                "app.evidence.hashing", fromlist=["content_hash"]
            ).content_hash(
                "REPRESENTATIVE DEMO TEXT: Hyperkalemia has been reported with "
                "concomitant use of ACE inhibitors and potassium-sparing diuretics, "
                "potassium supplements, or potassium-containing salt substitutes."
            ),
            source_url="https://dailymed.nlm.nih.gov/dailymed/",
            retrieved_at=retrieved_at,
            metadata={
                "set_id": "",
                "effective_time": "",
                "application_number": "",
                "section": "warnings",
                "fallback": "true",
            },
        )
    records.append(label_record)

    # --- PubMed: one abstract about ACE-inhibitor hyperkalemia ---
    try:
        pmids = esearch(
            "ACE inhibitor hyperkalemia",
            http_get=http_get,  # type: ignore[arg-type]
            retmax=1,
            throttle=TokenBucketRateLimiter(rate_per_sec=default_rate_per_sec(api_key=None)),
        )
        pubmed_records = (
            efetch(
                pmids,
                http_get=http_get,  # type: ignore[arg-type]
                retrieved_at=retrieved_at,
                throttle=TokenBucketRateLimiter(rate_per_sec=default_rate_per_sec(api_key=None)),
            )
            if pmids
            else []
        )
    except EvidenceError as exc:
        print(f"[skip] PubMed esearch/efetch: {exc}")
        pubmed_records = []

    if pubmed_records and pubmed_records[0].content.strip():
        records.append(pubmed_records[0])
        print(f"[ok] PubMed -> {pubmed_records[0].id}")
    else:
        fell_back.append("pubmed:ace-inhibitor-hyperkalemia")
        fallback_content = (
            "REPRESENTATIVE DEMO TEXT: Hyperkalemia is a recognized risk of "
            "angiotensin-converting enzyme inhibitor therapy, particularly in "
            "patients with renal impairment or those receiving concomitant "
            "potassium-sparing agents."
        )
        records.append(
            EvidenceRecord(
                id="pubmed:REPRESENTATIVE",
                tier=__import__("app.evidence.models", fromlist=["EvidenceTier"]).EvidenceTier.LITERATURE,
                title="ACE inhibitor hyperkalemia (REPRESENTATIVE DEMO TEXT)",
                publisher="REPRESENTATIVE DEMO TEXT",
                jurisdiction=__import__(
                    "app.evidence.models", fromlist=["Jurisdiction"]
                ).Jurisdiction.NOT_APPLICABLE,
                publication_date=None,
                version=None,
                content=fallback_content,
                content_hash=__import__(
                    "app.evidence.hashing", fromlist=["content_hash"]
                ).content_hash(fallback_content),
                source_url="https://pubmed.ncbi.nlm.nih.gov/",
                retrieved_at=retrieved_at,
                metadata={"publication_types": "", "mesh": "", "doi": "", "fallback": "true"},
            )
        )

    # --- Guideline pack PENDING placeholder ---
    records.extend(load_guideline_pack(GUIDELINE_PACK_DIR, retrieved_at=retrieved_at))

    snapshot = build_snapshot(records, created_at=retrieved_at)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(json.loads(snapshot.model_dump_json()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"snapshot {snapshot.snapshot_id}: {len(records)} record(s) -> {OUTPUT_PATH}")
    if fell_back:
        print(f"FELL BACK to representative demo text for: {fell_back}")
    else:
        print("all records fetched live -- no fallback used")


if __name__ == "__main__":
    main()
