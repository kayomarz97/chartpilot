"""Phase 17 resilience tests: an upstream model outage must never crash
`run_patient` and must never look like an empty "no findings" result.

Spec §6: an upstream (Gemini) failure fails the patient run CLOSED to a
FAILED `PatientRunResult` with `error` set -- it never propagates as an
uncaught exception and never silently produces zero findings. These tests
simulate a hard outage (any exception from `GeminiClient.create`, standing
in for a transient 5xx/"high demand" error that has already exhausted the
bounded retry in `app.agent.gemini.GeminiInteractionsClient`) at each of the
two model-call sites in `app.pipeline.runner.run_patient` and assert the
run still returns normally with a FAILED summary.

Hermetic: `RaisingGeminiClient` never touches the network. Model A success
in the second test is driven by the same cassette-backed `FakeGeminiClient`
wiring as `tests/unit/test_pipeline_demo.py` (Phase 14).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.model_pin import load_model_pin
from app.agent.protocol import InteractionResult
from app.fhir.transport import LocalFixtureTransport
from app.gate.models import PatientStatus
from app.pipeline.demo_evidence import load_demo_snapshot
from app.pipeline.runner import run_patient
from app.storage.inmemory import InMemoryRunRepository
from tests.support.fake_gemini import FakeGeminiClient

_DEMO_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
_CASSETTES_DIR = _DEMO_DIR / "cassettes"
_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

_OUTAGE_MESSAGE = "simulated model outage"


class RaisingGeminiClient:
    """A `GeminiClient` whose `create` always raises -- stands in for a
    transient Gemini 5xx/"high demand" error that has exhausted every retry
    in `GeminiInteractionsClient.create`, so it reaches `run_patient` as a
    plain exception. `list_models` returns the real pinned model ids so this
    fake is a faithful `GeminiClient` in every other respect."""

    def list_models(self) -> list[str]:
        pin = load_model_pin()
        return [pin.model_a_id, pin.model_b_id]

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        raise RuntimeError(_OUTAGE_MESSAGE)


def _load_cassette(patient_key: str) -> dict[str, Any]:
    return json.loads((_CASSETTES_DIR / f"patient_{patient_key}.json").read_text(encoding="utf-8"))


def _model_a_client(cassette: dict[str, Any], *, patient_id: str) -> FakeGeminiClient:
    output_text = json.dumps(cassette["model_a"])
    return FakeGeminiClient([(f"PATIENT_ID: {patient_id}", output_text)])


def test_model_a_outage_fails_closed_not_crash() -> None:
    """A Model A outage returns a FAILED `PatientRunResult` -- it must never
    raise out of `run_patient` and must never come back looking like a
    legitimate empty-findings COMPLETED run."""
    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)

    result = run_patient(
        patient_bundle_ref="patient_a.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=RaisingGeminiClient(),
        model_b=RaisingGeminiClient(),
        clock=lambda: _NOW,
        repo=InMemoryRunRepository(),
        run_id="resilience-model-a-outage",
    )

    assert result.summary.status == PatientStatus.FAILED
    assert result.error is not None
    assert _OUTAGE_MESSAGE in result.error
    assert result.findings == ()


def test_model_b_outage_fails_closed_not_crash() -> None:
    """Model A succeeds (real demo cassette), but Model B (the independent
    reviewer) hits an outage -- the run must still fail closed to FAILED at
    INDEPENDENT_REVIEW rather than crashing or reporting "no findings"."""
    cassette = _load_cassette("a")
    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)

    result = run_patient(
        patient_bundle_ref="patient_a.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=_model_a_client(cassette, patient_id="patient-a"),
        model_b=RaisingGeminiClient(),
        clock=lambda: _NOW,
        repo=InMemoryRunRepository(),
        run_id="resilience-model-b-outage",
    )

    assert result.summary.status == PatientStatus.FAILED
    assert result.error is not None
    assert _OUTAGE_MESSAGE in result.error
