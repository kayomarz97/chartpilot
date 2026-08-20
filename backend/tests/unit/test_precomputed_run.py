"""Tests for the Phase 17 precomputed multi-patient demo run (spec §50).

Hermetic: exercises `app.pipeline.precomputed.build_precomputed_run` with the
same `FakeGeminiClient` + cassette wiring `test_pipeline_demo.py` uses, and
`load_precomputed_run` against the COMMITTED
`tests/fixtures/demo/precomputed_run.json` built by
`scripts/build_precomputed_run.py` -- no network access, no live Gemini call.

NOTE on the fixture's actual per-patient statuses (verified directly against
the committed cassettes, not assumed): Patient C -- not A -- is the one demo
patient whose only claim is `REQUIRES_REVIEW`, so Patient C alone reaches
`PatientStatus.FLAGGED_FOR_REVIEW` (mirrors
`test_pipeline_demo.py::test_patient_c_routes_to_requires_review`). Patient A
reaches `COMPLETED` with one `VERIFIED` CRITICAL finding (mirrors
`test_pipeline_demo.py::test_patient_a_has_high_priority_verified_or_review_finding`,
which itself only requires VERIFIED-or-REQUIRES_REVIEW at CRITICAL/HIGH
severity, not any particular overall `PatientStatus`). These tests assert
what the pipeline actually produces from the committed cassettes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent.protocol import GeminiClient
from app.pipeline.precomputed import build_precomputed_run, load_precomputed_run
from tests.support.fake_gemini import FakeGeminiClient

_DEMO_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
_PRECOMPUTED_PATH = _DEMO_DIR / "precomputed_run.json"


def _model_a_factory(cassette: dict[str, Any], patient_id: str) -> GeminiClient:
    output_text = json.dumps(cassette["model_a"])
    return FakeGeminiClient([(f"PATIENT_ID: {patient_id}", output_text)])


def _model_b_factory(cassette: dict[str, Any]) -> GeminiClient:
    statements_by_id = {c["claim_id"]: c["statement"] for c in cassette["model_a"]["claims"]}
    responses = [
        (statements_by_id[entry["claim_id"]], json.dumps(entry["verdict"]))
        for entry in cassette["model_b"]
    ]
    return FakeGeminiClient(responses)


def _patient(run: dict[str, Any], patient_id: str) -> dict[str, Any]:
    for patient in run["patients"]:
        if patient["patient_id"] == patient_id:
            return patient  # type: ignore[no-any-return]
    raise AssertionError(
        f"no patient {patient_id!r} in run: {[p['patient_id'] for p in run['patients']]}"
    )


def test_committed_fixture_loads_with_exactly_five_patients() -> None:
    run = load_precomputed_run()

    assert run["run_id"]
    assert isinstance(run["generated_note"], str) and run["generated_note"]
    assert len(run["patients"]) == 5
    assert [p["patient_id"] for p in run["patients"]] == [
        "patient-a",
        "patient-b",
        "patient-c",
        "patient-d",
        "patient-e",
    ]


def test_committed_fixture_patient_a_has_high_priority_finding() -> None:
    run = load_precomputed_run()
    patient_a = _patient(run, "patient-a")

    assert patient_a["error"] is None
    assert patient_a["status"] not in ("queued", "running")
    assert patient_a["findings"], "patient A must produce at least one finding"
    high_priority = [f for f in patient_a["findings"] if f["severity"] in ("critical", "high")]
    assert high_priority, f"expected a high-priority finding, got {patient_a['findings']!r}"


def test_committed_fixture_patient_b_has_no_unresolved_hyperkalemia_finding() -> None:
    run = load_precomputed_run()
    patient_b = _patient(run, "patient-b")

    for finding in patient_b["findings"]:
        assert finding["severity"] not in ("critical", "high")
        statement_lower = finding["statement"].lower()
        assert (
            "6.3" not in statement_lower
            or "resolved" in statement_lower
            or ("normal" in statement_lower or "4.1" in statement_lower)
        )


def test_committed_fixture_precomputed_path_default_matches_disk_location() -> None:
    """Sanity check that `load_precomputed_run`'s default path resolves to
    the same file `scripts/build_precomputed_run.py` writes."""
    assert _PRECOMPUTED_PATH.exists()
    on_disk = json.loads(_PRECOMPUTED_PATH.read_text(encoding="utf-8"))
    assert on_disk == load_precomputed_run()


def test_build_precomputed_run_is_deterministic() -> None:
    """Building the precomputed run twice, from the same cassettes/fixtures,
    yields byte-identical JSON output (spec §50 determinism requirement)."""
    run_1 = build_precomputed_run(_model_a_factory, _model_b_factory)
    run_2 = build_precomputed_run(_model_a_factory, _model_b_factory)

    assert json.dumps(run_1, sort_keys=True) == json.dumps(run_2, sort_keys=True)


def test_build_precomputed_run_matches_committed_fixture() -> None:
    """The committed fixture is exactly what `build_precomputed_run` produces
    right now -- i.e. it has not gone stale relative to the cassettes it was
    built from."""
    freshly_built = build_precomputed_run(_model_a_factory, _model_b_factory)

    assert json.dumps(freshly_built, sort_keys=True) == json.dumps(
        load_precomputed_run(), sort_keys=True
    )
