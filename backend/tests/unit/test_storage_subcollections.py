"""Tests for the storage-layer data-model separation (spec §44): after
`finalize_patient_result`, detailed claim/evidence artifacts live only in their
subcollections -- keyed to the right `run_id`/`patient_id` -- and are never
inlined into the compact patient summary doc.
"""

from __future__ import annotations

from app.gate.models import PatientStage, PatientStatus
from app.storage.inmemory import InMemoryRunRepository
from app.storage.models import (
    claims_collection_path,
    clinician_actions_collection_path,
    evidence_collection_path,
)
from app.storage.two_phase import finalize_patient_result

_RUN_ID = "run-1"
_PATIENT_ID = "patient-1"
_CLAIMS = [
    ("claim-1", {"text": "potassium 5.9 mmol/L"}),
    ("claim-2", {"text": "creatinine 1.4 mg/dL"}),
]
_EVIDENCE = [
    ("ev-1", {"source": "openfda", "ref": "abc"}),
]


def _finalize(repo: InMemoryRunRepository) -> None:
    finalize_patient_result(
        repo,
        run_id=_RUN_ID,
        patient_id=_PATIENT_ID,
        evidence_snapshot_id="snap-123",
        stage=PatientStage.FINAL_VALIDATION,
        claims=_CLAIMS,
        evidence=_EVIDENCE,
        terminal_status=PatientStatus.COMPLETED,
    )


def test_claims_land_in_the_correct_subcollection_path() -> None:
    repo = InMemoryRunRepository()
    _finalize(repo)
    stored = dict(repo.read_documents(claims_collection_path(_RUN_ID, _PATIENT_ID)))
    assert stored == dict(_CLAIMS)


def test_evidence_lands_in_the_correct_subcollection_path() -> None:
    repo = InMemoryRunRepository()
    _finalize(repo)
    stored = dict(repo.read_documents(evidence_collection_path(_RUN_ID, _PATIENT_ID)))
    assert stored == dict(_EVIDENCE)


def test_paths_are_bound_to_run_and_patient_id_not_shared() -> None:
    repo = InMemoryRunRepository()
    _finalize(repo)
    other_run = repo.read_documents(claims_collection_path("run-2", _PATIENT_ID))
    other_patient = repo.read_documents(claims_collection_path(_RUN_ID, "patient-2"))
    assert other_run == []
    assert other_patient == []


def test_summary_carries_evidence_snapshot_id() -> None:
    repo = InMemoryRunRepository()
    _finalize(repo)
    summary = repo.get_patient_summary(_RUN_ID, _PATIENT_ID)
    assert summary is not None
    assert summary.evidence_snapshot_id == "snap-123"


def test_clinician_actions_collection_path_is_a_sibling_of_claims_and_evidence() -> None:
    """(Phase B, spec §53) The clinician-labels subcollection lives under the
    same private per-patient tree as claims/evidence -- not the public
    `presentations` collection -- and is bound to `(run_id, patient_id)`
    exactly like `claims_collection_path`/`evidence_collection_path`."""
    path = clinician_actions_collection_path(_RUN_ID, _PATIENT_ID)
    assert path == f"runs/{_RUN_ID}/patients/{_PATIENT_ID}/clinician_actions"
    assert path != claims_collection_path(_RUN_ID, _PATIENT_ID)
    assert path != evidence_collection_path(_RUN_ID, _PATIENT_ID)
    assert clinician_actions_collection_path("run-2", _PATIENT_ID) != path
    assert clinician_actions_collection_path(_RUN_ID, "patient-2") != path


def test_summary_never_inlines_claim_or_evidence_payloads() -> None:
    repo = InMemoryRunRepository()
    _finalize(repo)
    summary = repo.get_patient_summary(_RUN_ID, _PATIENT_ID)
    assert summary is not None
    summary_fields = summary.model_dump()
    # The summary is a fixed, small schema: no field on it could hold a claim/
    # evidence payload (only counts and IDs), and the claim/evidence text itself
    # never appears anywhere in the serialized summary.
    assert "claims" not in summary_fields
    assert "evidence" not in summary_fields
    serialized = str(summary_fields)
    assert "potassium" not in serialized
    assert "creatinine" not in serialized
