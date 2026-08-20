"""Build the precomputed, deterministic, multi-patient demo run (spec §50).

`build_precomputed_run` chains all 5 demo patients (A-E) through
`app.pipeline.runner.run_patient`, the exact same hermetic wiring
`tests/unit/test_pipeline_demo.py` uses (a per-patient cassette-driven
`GeminiClient` fake + the committed FHIR bundle fixtures + the committed
evidence snapshot), and folds the results into one compact,
JSON-serializable dict a UI can render instantly with zero pipeline latency.

`model_a_factory`/`model_b_factory` are dependency-injected rather than this
module importing `tests.support.fake_gemini.FakeGeminiClient` directly:
`app/` must never import from `tests/`. `scripts/build_precomputed_run.py`
and `tests/unit/test_precomputed_run.py` both supply factories wired
identically to `test_pipeline_demo.py`'s `_model_a_client`/`_model_b_client`.

Deterministic by construction: the clock is a fixed constant (never
`datetime.now()`), the cassettes/fixtures are committed and immutable, and
`run_patient` itself is already covered by
`test_pipeline_demo.py::test_determinism_same_patient_twice_yields_identical_deterministic_output`.
`test_precomputed_run.py` asserts the whole-run-level determinism directly:
building twice yields byte-identical `json.dumps(...)` output.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.protocol import GeminiClient
from app.fhir.transport import LocalFixtureTransport
from app.pipeline.demo_evidence import load_demo_snapshot
from app.pipeline.models import FindingResult, PatientRunResult
from app.pipeline.runner import run_patient
from app.storage.inmemory import InMemoryRunRepository

__all__ = [
    "ModelAFactory",
    "ModelBFactory",
    "build_precomputed_run",
    "load_precomputed_run",
]

#: Builds one patient's Model A `GeminiClient` from that patient's cassette
#: dict and patient id -- mirrors `test_pipeline_demo.py`'s `_model_a_client`.
ModelAFactory = Callable[[dict[str, Any], str], GeminiClient]

#: Builds one patient's Model B `GeminiClient` from that patient's cassette
#: dict -- mirrors `test_pipeline_demo.py`'s `_model_b_client`.
ModelBFactory = Callable[[dict[str, Any]], GeminiClient]

#: `app/pipeline/precomputed.py` -> `app/pipeline` -> `app` -> `backend`.
_DEMO_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo"
_DEFAULT_OUTPUT_PATH = _DEMO_DIR / "precomputed_run.json"

#: Fixed clock (spec §50: byte-identical output on every rebuild) -- matches
#: the constant `test_pipeline_demo.py` uses for the same reason.
_DEFAULT_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

#: (cassette/fixture key, expected `Patient.id`) for each of the 5 demo
#: patients, in the fixed order they are run and reported in.
_PATIENTS: tuple[tuple[str, str], ...] = (
    ("a", "patient-a"),
    ("b", "patient-b"),
    ("c", "patient-c"),
    ("d", "patient-d"),
    ("e", "patient-e"),
)


def _load_cassette(cassettes_dir: Path, patient_key: str) -> dict[str, Any]:
    raw: Any = json.loads(
        (cassettes_dir / f"patient_{patient_key}.json").read_text(encoding="utf-8")
    )
    data: dict[str, Any] = raw
    return data


def _finding_dict(finding: FindingResult) -> dict[str, Any]:
    claim = finding.claim
    return {
        "claim_id": claim.claim_id,
        "claim_type": claim.claim_type.value,
        "statement": claim.statement,
        "severity": claim.severity.value if claim.severity is not None else None,
        "confidence": claim.confidence,
        "recommended_action": claim.recommended_action,
        "verdict": finding.verdict.value,
        "model_b_finding": (
            finding.model_b_verdict.finding.value if finding.model_b_verdict is not None else None
        ),
    }


def _patient_dict(result: PatientRunResult) -> dict[str, Any]:
    return {
        "patient_id": result.patient_id,
        "status": result.summary.status.value,
        "stage": result.summary.stage.value,
        "error": result.error,
        "findings": [_finding_dict(finding) for finding in result.findings],
        "timeline": list(result.timeline_events),
    }


def build_precomputed_run(
    model_a_factory: ModelAFactory,
    model_b_factory: ModelBFactory,
    *,
    demo_dir: Path | None = None,
    run_id: str = "precomputed-demo-run",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run all 5 demo patients (A-E) and return one compact precomputed-run dict.

    Shape: `{run_id, generated_note, patients: [{patient_id, status, stage,
    error, findings: [...], timeline: [...]}, ...]}`, `patients` always in
    the fixed A-E order (`_PATIENTS`). Every field is a plain str/bool/None/
    list/dict -- the return value is always `json.dumps`-able as-is.
    """
    resolved_demo_dir = demo_dir if demo_dir is not None else _DEMO_DIR
    cassettes_dir = resolved_demo_dir / "cassettes"
    resolved_now = now if now is not None else _DEFAULT_NOW
    transport = LocalFixtureTransport(resolved_demo_dir)
    snapshot = load_demo_snapshot()

    def _fixed_clock() -> datetime:
        return resolved_now

    patients: list[dict[str, Any]] = []
    for patient_key, patient_id in _PATIENTS:
        cassette = _load_cassette(cassettes_dir, patient_key)
        result = run_patient(
            patient_bundle_ref=f"patient_{patient_key}.json",
            fhir_transport=transport,
            snapshot=snapshot,
            model_a=model_a_factory(cassette, patient_id),
            model_b=model_b_factory(cassette),
            clock=_fixed_clock,
            repo=InMemoryRunRepository(),
            run_id=f"{run_id}-{patient_key}",
        )
        patients.append(_patient_dict(result))

    return {
        "run_id": run_id,
        "generated_note": (
            "Precomputed from committed demo fixtures/cassettes (spec §50) -- "
            "hermetic and deterministic, no network access at generation time. "
            "For instant UI rendering only; not a substitute for a live pipeline run."
        ),
        "patients": patients,
    }


def load_precomputed_run(path: Path | None = None) -> dict[str, Any]:
    """Load the committed precomputed-run JSON fixture from disk."""
    target = path if path is not None else _DEFAULT_OUTPUT_PATH
    data: Any = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"precomputed run fixture at {target} is not a JSON object")
    return data
