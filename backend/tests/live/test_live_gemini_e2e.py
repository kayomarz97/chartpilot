"""Live end-to-end pipeline run against the REAL Gemini API (spec §23).

This is the one place in the whole suite that is deliberately NOT hermetic:
it builds real `GeminiInteractionsClient`s (Model A + Model B) and runs the
full `run_patient` pipeline against them over the network. Everything else in
`tests/` is driven by `FakeGeminiClient` cassettes precisely so this file can
be the single, clearly-labeled exception.

Excluded from `make check`/default `pytest tests` collection by two
independent guards:
  1. `pyproject.toml`'s `addopts` includes `-m "not live"`, and every test
     here is `@pytest.mark.live`.
  2. `pyproject.toml`'s `addopts` includes `--disable-socket`, which blocks
     all real network sockets; this module additionally opts back in with
     `@pytest.mark.enable_socket` (pytest-socket) so it can actually reach
     the API when deliberately invoked with `-m live`.

Skips cleanly (never fails) when `GEMINI_API_KEY` is not set in the
environment -- e.g. in CI, where no key exists -- so it is safe to leave in
the tree. See `README.md` in this directory for the exact command to run it
on purpose. Costs real tokens; never run as part of routine development.

Only ROBUST, non-prose properties are asserted (run completes with no error,
reaches the terminal PERSISTED stage, and produces at least one finding) --
never exact model wording or an exact finding count, since model output
varies run to run (spec §23).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agent.gemini import GeminiInteractionsClient
from app.fhir.transport import LocalFixtureTransport
from app.gate.models import PatientStage, PatientStatus
from app.pipeline.demo_evidence import load_demo_snapshot
from app.pipeline.runner import run_patient
from app.storage.inmemory import InMemoryRunRepository

if not os.environ.get("GEMINI_API_KEY"):
    pytest.skip(
        "GEMINI_API_KEY not set in the environment -- skipping live Gemini "
        "e2e test (see tests/live/README.md to run it on purpose)",
        allow_module_level=True,
    )

_DEMO_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
_MODEL_A_ID = "gemini-3.7-flash"
_MODEL_B_ID = "gemini-3.5-flash"


@pytest.mark.live
@pytest.mark.enable_socket
def test_live_pipeline_runs_patient_a_end_to_end() -> None:
    """The full pipeline, run for real, reaches PERSISTED with >=1 finding."""
    api_key = os.environ["GEMINI_API_KEY"]
    model_a = GeminiInteractionsClient(api_key=api_key, model_id=_MODEL_A_ID)
    model_b = GeminiInteractionsClient(api_key=api_key, model_id=_MODEL_B_ID)

    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)

    result = run_patient(
        patient_bundle_ref="patient_a.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=model_a,
        model_b=model_b,
        clock=lambda: datetime.now(UTC),
        repo=InMemoryRunRepository(),
        run_id="live-e2e-run",
    )

    assert result.error is None, f"live pipeline run failed: {result.error!r}"
    assert result.summary.status != PatientStatus.RUNNING
    assert result.summary.status != PatientStatus.QUEUED
    assert result.summary.stage == PatientStage.PERSISTED
    assert result.findings, "expected at least one finding from the live run"
