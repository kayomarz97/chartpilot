"""Hermetic tests for the Phase 19 live composition root (`app.api.composition`).

Mirrors `tests/unit/test_pipeline_demo.py`'s cassette-driven `FakeGeminiClient`
pattern: `run_demo_patient` is driven end to end against the REAL packaged
`app/demo_data` fixtures (never `tests/fixtures/demo/` directly), which is
what proves that directory's packaging is complete for Phase 19's live
per-patient handler -- a missing fixture file would fail these tests
immediately, exactly like it would fail the deployed worker.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
from app.api import composition as api_composition
from app.api import routes as api_routes
from app.api.auth import require_oidc
from app.api.composition import (
    DEMO_DATA_DIR,
    DEMO_PATIENT_IDS,
    DemoAppointmentSource,
    build_live_queue,
    run_demo_patient,
)
from app.config import get_settings
from app.gate.models import PatientStage, PatientStatus, is_terminal
from app.improve.inmemory_ledger import InMemoryPromotionLedger
from app.improve.models import ImproveTarget
from app.improve.promote import FilePromotionLedger
from app.improve.registry import resolve_artifact
from app.main import app
from app.storage.inmemory import InMemoryRunRepository
from app.tasks.cloud_tasks import CloudTasksQueue
from app.tasks.models import Checkpoint, RunTask
from tests.support.fake_gemini import FakeGeminiClient

_CASSETTES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo" / "cassettes"
_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
}


def _load_cassette(patient_key: str) -> dict[str, Any]:
    return json.loads((_CASSETTES_DIR / f"patient_{patient_key}.json").read_text(encoding="utf-8"))


def _model_a_client(cassette: dict[str, Any], *, patient_id: str) -> FakeGeminiClient:
    output_text = json.dumps(cassette["model_a"])
    return FakeGeminiClient([(f"PATIENT_ID: {patient_id}", output_text)])


def _model_b_client(cassette: dict[str, Any]) -> FakeGeminiClient:
    statements_by_id = {c["claim_id"]: c["statement"] for c in cassette["model_a"]["claims"]}
    responses = [
        (statements_by_id[entry["claim_id"]], json.dumps(entry["verdict"]))
        for entry in cassette["model_b"]
    ]
    return FakeGeminiClient(responses)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# run_demo_patient: packaging completeness + terminal outcome
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "patient_key,patient_id",
    [
        ("a", "patient-a"),
        ("b", "patient-b"),
        ("c", "patient-c"),
        ("d", "patient-d"),
        ("e", "patient-e"),
    ],
)
def test_run_demo_patient_completes_for_every_packaged_patient(
    patient_key: str, patient_id: str
) -> None:
    """Every packaged demo patient runs end to end against `app/demo_data`
    and reaches a terminal `Checkpoint` -- proves the packaging in
    `app/demo_data` (not `tests/fixtures/demo`) is complete."""
    cassette = _load_cassette(patient_key)
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run", patient_id=patient_id)

    checkpoint = run_demo_patient(
        task,
        model_a=_model_a_client(cassette, patient_id=patient_id),
        model_b=_model_b_client(cassette),
        repo=repo,
        clock=lambda: _NOW,
    )

    assert is_terminal(checkpoint.status)
    assert checkpoint.current_stage == PatientStage.PERSISTED
    assert checkpoint.run_id == "test-run"
    assert checkpoint.patient_id == patient_id
    assert checkpoint.last_success_at is not None

    summary = repo.get_patient_summary("test-run", patient_id)
    assert summary is not None
    assert summary.stage == PatientStage.PERSISTED


def test_demo_data_dir_contains_every_packaged_patient_bundle() -> None:
    """Sanity check: `DEMO_DATA_DIR` actually contains the fixtures the
    handler needs (belt-and-braces alongside the parametrized run above)."""
    assert DEMO_DATA_DIR.is_dir()
    assert (DEMO_DATA_DIR / "evidence_snapshot.json").is_file()
    for patient_id in DEMO_PATIENT_IDS:
        bundle_path = DEMO_DATA_DIR / f"{patient_id.replace('-', '_')}.json"
        assert bundle_path.is_file(), f"missing packaged bundle for {patient_id!r}"


# --------------------------------------------------------------------------
# Idempotency (spec §46)
# --------------------------------------------------------------------------


def test_run_demo_patient_is_idempotent_on_redelivery() -> None:
    """A second call with the same repo (simulating a Cloud Tasks
    redelivery) must NOT re-invoke the model, and must return the same
    terminal outcome."""
    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run", patient_id="patient-a")

    model_a_1 = _model_a_client(cassette, patient_id="patient-a")
    model_b_1 = _model_b_client(cassette)
    first = run_demo_patient(
        task, model_a=model_a_1, model_b=model_b_1, repo=repo, clock=lambda: _NOW
    )
    assert is_terminal(first.status)
    assert len(model_a_1.calls) == 1

    # A fresh pair of fakes with NO cassette responses at all: if
    # `run_demo_patient` tried to call the model again, `FakeGeminiClient`
    # would raise `AssertionError` on the very first call -- so a passing
    # second call here is itself the proof the model was never re-invoked.
    model_a_2 = FakeGeminiClient([])
    model_b_2 = FakeGeminiClient([])
    second = run_demo_patient(
        task, model_a=model_a_2, model_b=model_b_2, repo=repo, clock=lambda: _NOW
    )

    assert is_terminal(second.status)
    assert second.status == first.status
    assert second.current_stage == first.current_stage
    assert model_a_2.calls == []
    assert model_b_2.calls == []


# --------------------------------------------------------------------------
# model_a_system_instruction pass-through (Phase C step (b))
# --------------------------------------------------------------------------


def test_run_demo_patient_default_uses_pinned_model_a_instruction() -> None:
    """No `model_a_system_instruction` given -> byte-identical to before
    this parameter existed: Model A's `.create` call is driven by the
    pinned `MODEL_A_SYSTEM_INSTRUCTION` constant, unchanged."""
    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run-default-instruction", patient_id="patient-a")
    model_a = _model_a_client(cassette, patient_id="patient-a")

    checkpoint = run_demo_patient(
        task, model_a=model_a, model_b=_model_b_client(cassette), repo=repo, clock=lambda: _NOW
    )

    assert is_terminal(checkpoint.status)
    assert len(model_a.calls) == 1
    assert model_a.calls[0].startswith(MODEL_A_SYSTEM_INSTRUCTION)


def test_run_demo_patient_explicit_override_reaches_model_a() -> None:
    """An explicit `model_a_system_instruction` override reaches Model A's
    `.create` call INSTEAD of the pinned constant."""
    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run-override-instruction", patient_id="patient-a")
    model_a = _model_a_client(cassette, patient_id="patient-a")
    override = "OVERRIDE SYSTEM INSTRUCTION FOR TESTING -- not the pinned constant."

    checkpoint = run_demo_patient(
        task,
        model_a=model_a,
        model_b=_model_b_client(cassette),
        repo=repo,
        clock=lambda: _NOW,
        model_a_system_instruction=override,
    )

    assert is_terminal(checkpoint.status)
    assert len(model_a.calls) == 1
    assert model_a.calls[0].startswith(override)
    assert not model_a.calls[0].startswith(MODEL_A_SYSTEM_INSTRUCTION)


def test_run_demo_patient_resolves_promoted_prompt_from_ledger(tmp_path: Path) -> None:
    """Wiring test: `resolve_artifact` over a `PromotionLedger` with an
    active promoted `MODEL_A_PROMPT`, passed through to `run_demo_patient`,
    drives Model A with the PROMOTED value -- not the pinned constant."""
    ledger = FilePromotionLedger(tmp_path)
    promoted_prompt = "PROMOTED MODEL A PROMPT -- from the ledger, not the pinned constant."
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT,
        promoted_prompt,
        version="v1",
        rationale="test promotion",
        now=_NOW,
    )
    resolved = resolve_artifact(
        ImproveTarget.MODEL_A_PROMPT, MODEL_A_SYSTEM_INSTRUCTION, ledger=ledger
    )
    assert resolved == promoted_prompt

    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run-ledger-promoted", patient_id="patient-a")
    model_a = _model_a_client(cassette, patient_id="patient-a")

    checkpoint = run_demo_patient(
        task,
        model_a=model_a,
        model_b=_model_b_client(cassette),
        repo=repo,
        clock=lambda: _NOW,
        model_a_system_instruction=resolved,
    )

    assert is_terminal(checkpoint.status)
    assert model_a.calls[0].startswith(promoted_prompt)


def test_run_demo_patient_resolves_pinned_default_from_empty_ledger(tmp_path: Path) -> None:
    """The same wiring with an EMPTY ledger resolves back to the pinned
    constant -- byte-identical to not consulting the ledger at all."""
    ledger = FilePromotionLedger(tmp_path)
    resolved = resolve_artifact(
        ImproveTarget.MODEL_A_PROMPT, MODEL_A_SYSTEM_INSTRUCTION, ledger=ledger
    )
    assert resolved == MODEL_A_SYSTEM_INSTRUCTION

    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()
    task = RunTask(run_id="test-run-ledger-empty", patient_id="patient-a")
    model_a = _model_a_client(cassette, patient_id="patient-a")

    checkpoint = run_demo_patient(
        task,
        model_a=model_a,
        model_b=_model_b_client(cassette),
        repo=repo,
        clock=lambda: _NOW,
        model_a_system_instruction=resolved,
    )

    assert is_terminal(checkpoint.status)
    assert model_a.calls[0].startswith(MODEL_A_SYSTEM_INSTRUCTION)


# --------------------------------------------------------------------------
# _resolve_live_model_a_system_instruction: the actual resolution helper
# `live_process_patient_handler` calls. It builds a real
# `FirestorePromotionLedger` internally -- these tests monkeypatch that
# module-level name to a fake/raising stand-in so nothing ever touches a
# real Firestore project (per `FirestorePromotionLedger`'s own `# VERIFY-LIVE`
# markers, which no hermetic test may exercise).
# --------------------------------------------------------------------------


def test_resolve_live_model_a_system_instruction_default_with_empty_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty ledger (true of every deployment before any promotion) ->
    the pinned `MODEL_A_SYSTEM_INSTRUCTION`, byte-identical to before the
    ledger-consuming wiring existed."""
    _set_required_env(monkeypatch)
    monkeypatch.setattr(
        api_composition, "FirestorePromotionLedger", lambda **_kwargs: InMemoryPromotionLedger()
    )

    resolved = api_composition._resolve_live_model_a_system_instruction(get_settings())

    assert resolved == MODEL_A_SYSTEM_INSTRUCTION


def test_resolve_live_model_a_system_instruction_returns_promoted_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ledger with an active promoted `MODEL_A_PROMPT` -> that promoted
    value, not the pinned constant."""
    _set_required_env(monkeypatch)
    fake_ledger = InMemoryPromotionLedger()
    promoted_prompt = "LIVE-RESOLVED PROMOTED PROMPT -- from the ledger."
    fake_ledger.promote(
        ImproveTarget.MODEL_A_PROMPT,
        promoted_prompt,
        version="v1",
        rationale="test promotion",
        now=_NOW,
    )
    monkeypatch.setattr(api_composition, "FirestorePromotionLedger", lambda **_kwargs: fake_ledger)

    resolved = api_composition._resolve_live_model_a_system_instruction(get_settings())

    assert resolved == promoted_prompt


def test_resolve_live_model_a_system_instruction_fails_safe_when_ledger_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ledger construction/read error (e.g. a Firestore auth/permission
    error) must never break a patient run -- it falls back to the pinned
    constant, exactly as if the ledger were empty."""
    _set_required_env(monkeypatch)

    def _raise(**_kwargs: object) -> InMemoryPromotionLedger:
        raise RuntimeError("simulated Firestore failure")

    monkeypatch.setattr(api_composition, "FirestorePromotionLedger", _raise)

    resolved = api_composition._resolve_live_model_a_system_instruction(get_settings())

    assert resolved == MODEL_A_SYSTEM_INSTRUCTION


# --------------------------------------------------------------------------
# DemoAppointmentSource
# --------------------------------------------------------------------------


def test_demo_appointment_source_returns_demo_patient_ids_for_any_day() -> None:
    source = DemoAppointmentSource()
    assert source.patients_for_day(date(2026, 8, 22)) == list(DEMO_PATIENT_IDS)
    assert source.patients_for_day(date(2099, 1, 1)) == list(DEMO_PATIENT_IDS)


# --------------------------------------------------------------------------
# build_live_queue
# --------------------------------------------------------------------------


def test_build_live_queue_with_all_settings_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TASKS_QUEUE", "test-queue")
    monkeypatch.setenv("WORKER_URL", "https://example.run.app/tasks/process-patient")
    monkeypatch.setenv("TASKS_INVOKER_SA", "invoker@test-project-id.iam.gserviceaccount.com")
    monkeypatch.setenv("OIDC_AUDIENCE", "https://example.run.app")

    queue = build_live_queue(get_settings())

    assert isinstance(queue, CloudTasksQueue)


def test_build_live_queue_missing_setting_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("WORKER_URL", "https://example.run.app/tasks/process-patient")
    monkeypatch.setenv("TASKS_INVOKER_SA", "invoker@test-project-id.iam.gserviceaccount.com")
    monkeypatch.setenv("OIDC_AUDIENCE", "https://example.run.app")
    monkeypatch.delenv("TASKS_QUEUE", raising=False)

    with pytest.raises(RuntimeError, match="tasks_queue"):
        build_live_queue(get_settings())


# --------------------------------------------------------------------------
# Endpoint integration: POST /tasks/process-patient with run_demo_patient
# --------------------------------------------------------------------------


def _accept_oidc() -> dict[str, str]:
    return {"sub": "test-caller"}


def test_process_patient_endpoint_with_demo_handler_returns_terminal_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("OIDC_AUDIENCE", "https://chartpilot-test.a.run.app")
    app.dependency_overrides[require_oidc] = _accept_oidc

    cassette = _load_cassette("a")
    repo = InMemoryRunRepository()

    def fake_handler(task: RunTask) -> Checkpoint:
        return run_demo_patient(
            task,
            model_a=_model_a_client(cassette, patient_id="patient-a"),
            model_b=_model_b_client(cassette),
            repo=repo,
            clock=lambda: _NOW,
        )

    app.dependency_overrides[api_routes.get_process_patient_handler] = lambda: fake_handler
    client = TestClient(app)
    task = RunTask(run_id="run-demo", patient_id="patient-a")

    response = client.post(
        "/tasks/process-patient",
        json=task.model_dump(mode="json"),
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_stage"] == PatientStage.PERSISTED.value
    assert body["status"] in {status.value for status in PatientStatus if is_terminal(status)}
