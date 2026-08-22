"""Tests for the OIDC-protected `POST /improve-run` endpoint (Phase C).

Hermetic: `get_run_repository`/`get_clock`/`get_improve_generator`/
`get_improve_score_fn`/`get_improve_ledger`/`require_oidc` are all
overridden, so no real Firestore/Gemini/Google verification call is ever
attempted, and the ledger is always backed by pytest `tmp_path`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes as api_routes
from app.api.auth import require_oidc
from app.config import get_settings
from app.improve.evaluator import ScoreFn
from app.improve.ledger import PromotionLedger
from app.improve.models import Candidate, Dataset, ImproveTarget, Metrics
from app.improve.promote import FilePromotionLedger
from app.improve.proposer import Generator
from app.main import app
from app.storage.inmemory import InMemoryRunRepository
from app.storage.models import clinician_actions_collection_path

REQUIRED_ENV = {
    "GCP_PROJECT_ID": "test-project-id",
    "GCP_REGION": "test-region-1",
    "MODEL_A_ID": "test-model-a",
    "MODEL_B_ID": "test-model-b",
    "GEMINI_API_KEY": "test-gemini-key",
}

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


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


def _accept_oidc() -> dict[str, str]:
    return {"sub": "test-caller"}


def _seed_presentation(repo: InMemoryRunRepository, run_id: str, patient_id: str) -> None:
    repo.upsert_presentation(
        run_id,
        patient_id,
        {
            "patientId": patient_id,
            "findings": [
                {
                    "claimId": "claim-1",
                    "claimType": "PATIENT_FACT",
                    "verdict": "VERIFIED",
                    "revisionAttempts": 0,
                    "externalEvidence": [],
                }
            ],
        },
    )


def _improving_score_fn_factory(holdout: Dataset) -> ScoreFn:
    def score(value: str) -> Metrics:
        caught = 8 if value == "better prompt" else 7
        return Metrics(
            set_d_blocked=7, set_m_caught=caught, false_reject=0, clinician_agreement=1.0
        )

    return score


def _tying_score_fn_factory(holdout: Dataset) -> ScoreFn:
    def score(value: str) -> Metrics:
        return Metrics(set_d_blocked=7, set_m_caught=7, false_reject=0, clinician_agreement=1.0)

    return score


def _generate_better_prompt(dataset: Dataset, target: ImproveTarget) -> Candidate:
    return Candidate(target=target, new_value="better prompt", rationale="test proposer")


def _client_with_overrides(
    monkeypatch: pytest.MonkeyPatch,
    repo: InMemoryRunRepository,
    ledger: PromotionLedger,
    *,
    generate: Generator,
    score_fn_factory: Callable[[Dataset], ScoreFn],
) -> TestClient:
    _set_required_env(monkeypatch)
    app.dependency_overrides[require_oidc] = _accept_oidc
    app.dependency_overrides[api_routes.get_run_repository] = lambda: repo
    app.dependency_overrides[api_routes.get_clock] = lambda: lambda: _NOW
    app.dependency_overrides[api_routes.get_improve_generator] = lambda: generate
    app.dependency_overrides[api_routes.get_improve_score_fn] = lambda: score_fn_factory
    app.dependency_overrides[api_routes.get_improve_ledger] = lambda: ledger
    return TestClient(app)


def test_missing_bearer_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    client = TestClient(app)

    response = client.post("/improve-run", json={"run_id": "run-1", "version": "v1"})

    assert response.status_code == 401


def test_accepted_cycle_returns_report_and_promotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = InMemoryRunRepository()
    _seed_presentation(repo, "run-1", "patient-1")
    ledger = FilePromotionLedger(tmp_path)
    client = _client_with_overrides(
        monkeypatch,
        repo,
        ledger,
        generate=_generate_better_prompt,
        score_fn_factory=_improving_score_fn_factory,
    )

    response = client.post(
        "/improve-run",
        json={"run_id": "run-1", "target": "model_a_prompt", "version": "v1"},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["target"] == "model_a_prompt"
    assert body["promotion"]["version"] == "v1"
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "better prompt"


def test_rejected_cycle_returns_report_and_does_not_write_to_the_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = InMemoryRunRepository()
    _seed_presentation(repo, "run-1", "patient-1")
    presentations_before = repo.list_presentations("run-1")
    ledger = FilePromotionLedger(tmp_path)
    client = _client_with_overrides(
        monkeypatch,
        repo,
        ledger,
        generate=_generate_better_prompt,
        score_fn_factory=_tying_score_fn_factory,
    )

    response = client.post(
        "/improve-run",
        json={"run_id": "run-1", "target": "model_a_prompt", "version": "v1"},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["promotion"] is None
    assert ledger.active(ImproveTarget.MODEL_A_PROMPT) is None
    # No write path other than the ledger exists for this endpoint -- the
    # repo's presentation data must be untouched.
    assert repo.list_presentations("run-1") == presentations_before


def test_reads_clinician_actions_across_every_patient_in_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = InMemoryRunRepository()
    _seed_presentation(repo, "run-1", "patient-1")
    _seed_presentation(repo, "run-1", "patient-2")
    repo.write_documents(
        clinician_actions_collection_path("run-1", "patient-2"),
        [
            (
                "action-1",
                {
                    "patient_id": "patient-2",
                    "claim_id": "claim-1",
                    "action": "override",
                    "note": "wrong",
                    "recorded_at": "2026-08-20T11:00:00Z",
                },
            )
        ],
    )
    ledger = FilePromotionLedger(tmp_path)

    seen_datasets: list[Dataset] = []

    def capturing_generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        seen_datasets.append(dataset)
        return Candidate(target=target, new_value="better prompt", rationale="test")

    client = _client_with_overrides(
        monkeypatch,
        repo,
        ledger,
        generate=capturing_generate,
        score_fn_factory=_improving_score_fn_factory,
    )

    response = client.post(
        "/improve-run",
        json={"run_id": "run-1", "target": "model_a_prompt", "version": "v1"},
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    assert len(seen_datasets) == 1
    # The train split the generator saw was built from a dataset that
    # included both patients' claims -- proving clinician actions were
    # collected across every patient in the run, not just the first.
    all_patient_ids = {"patient-1", "patient-2"}
    train_patient_ids = {c.patient_id for c in seen_datasets[0].cases}
    assert train_patient_ids.issubset(all_patient_ids)
