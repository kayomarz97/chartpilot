"""End-to-end tests for the Phase 14 demo pipeline (`app.pipeline.runner.run_patient`).

Hermetic: `FakeGeminiClient` below never touches the network -- it is driven
entirely by the per-patient cassette JSON files in
`tests/fixtures/demo/cassettes/`, and the evidence snapshot is the committed,
previously-fetched fixture loaded by `app.pipeline.demo_evidence`. Patients
A-E are the hand-authored FHIR bundles in `tests/fixtures/demo/patient_*.json`
(spec §51).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
from app.fhir.transport import LocalFixtureTransport
from app.gate.models import ClaimVerdict, PatientStatus
from app.pipeline.demo_evidence import load_demo_snapshot
from app.pipeline.models import PatientRunResult
from app.pipeline.runner import run_patient
from app.rules.models import Severity
from app.storage.inmemory import InMemoryRunRepository
from tests.support.fake_gemini import FakeGeminiClient

_DEMO_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "demo"
_CASSETTES_DIR = _DEMO_DIR / "cassettes"
_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _load_cassette(patient_key: str) -> dict[str, Any]:
    return json.loads((_CASSETTES_DIR / f"patient_{patient_key}.json").read_text(encoding="utf-8"))


def _model_a_client(cassette: dict[str, Any], *, patient_id: str) -> FakeGeminiClient:
    output_text = json.dumps(cassette["model_a"])
    return FakeGeminiClient([(f"PATIENT_ID: {patient_id}", output_text)])


def _model_b_client(cassette: dict[str, Any]) -> FakeGeminiClient:
    """Route each Model B call by the claim's own `statement` text.

    `ModelBPacket` (the blinded input Model B actually sees) carries
    `claim_statement` -- copied verbatim from `Claim.statement` by
    `build_model_b_packet` -- but no `claim_id` field at all (spec §21.1
    blinding). So cassette responses are keyed by `claim_id` for readability
    but routed here by looking up that claim's exact `statement` text, which
    IS guaranteed to appear verbatim in the serialized packet.
    """
    statements_by_id = {c["claim_id"]: c["statement"] for c in cassette["model_a"]["claims"]}
    responses = [
        (statements_by_id[entry["claim_id"]], json.dumps(entry["verdict"]))
        for entry in cassette["model_b"]
    ]
    return FakeGeminiClient(responses)


def _run(patient_key: str, patient_id: str) -> PatientRunResult:
    cassette = _load_cassette(patient_key)
    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)
    return run_patient(
        patient_bundle_ref=f"patient_{patient_key}.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=_model_a_client(cassette, patient_id=patient_id),
        model_b=_model_b_client(cassette),
        clock=lambda: _NOW,
        repo=InMemoryRunRepository(),
        run_id=f"demo-run-{patient_key}",
    )


_PATIENTS = [
    ("a", "patient-a"),
    ("b", "patient-b"),
    ("c", "patient-c"),
    ("d", "patient-d"),
    ("e", "patient-e"),
]


@pytest.mark.parametrize("patient_key,patient_id", _PATIENTS)
def test_all_patients_complete_without_error(patient_key: str, patient_id: str) -> None:
    """Every demo patient runs end to end and reaches a terminal status."""
    result = _run(patient_key, patient_id)

    assert result.patient_id == patient_id
    assert result.error is None
    assert result.summary.status != PatientStatus.RUNNING
    assert result.summary.status != PatientStatus.QUEUED


def test_patient_a_has_high_priority_verified_or_review_finding() -> None:
    result = _run("a", "patient-a")

    assert result.findings, "patient A must produce at least one finding"
    high_priority = [
        f
        for f in result.findings
        if f.claim.severity in (Severity.CRITICAL, Severity.HIGH)
        and f.verdict in (ClaimVerdict.VERIFIED, ClaimVerdict.REQUIRES_REVIEW)
    ]
    assert high_priority, f"expected a high-priority finding, got {result.findings!r}"

    # K_HIGH_RISK_001 must have actually fired for this patient.
    assert any(rule.verdict.value == "fired" for rule in result.rule_results)


def test_patient_b_has_no_unresolved_hyperkalemia_finding() -> None:
    result = _run("b", "patient-b")

    # The deterministic rule itself must not fire (the current value is normal).
    assert all(rule.verdict.value != "fired" for rule in result.rule_results)

    # No finding may assert unresolved/current hyperkalemia at CRITICAL/HIGH severity.
    for finding in result.findings:
        assert finding.claim.severity not in (Severity.CRITICAL, Severity.HIGH)
        statement_lower = finding.claim.statement.lower()
        assert (
            "6.3" not in statement_lower
            or "resolved" in statement_lower
            or ("normal" in statement_lower or "4.1" in statement_lower)
        )


def test_patient_c_routes_to_requires_review() -> None:
    result = _run("c", "patient-c")

    assert any(f.verdict == ClaimVerdict.REQUIRES_REVIEW for f in result.findings)
    # The ambiguous unit must have been caught at the rule layer too.
    assert any(rule.verdict.value == "insufficient_data" for rule in result.rule_results)


def test_patient_d_and_e_complete() -> None:
    result_d = _run("d", "patient-d")
    result_e = _run("e", "patient-e")

    assert result_d.error is None
    assert result_e.error is None


def test_two_patients_produce_verified_claims_with_real_citation_chain() -> None:
    """At least two patients (A and E) must have a VERIFIED claim whose
    citation chain actually verified against the real demo evidence snapshot."""
    verified_patients: list[str] = []
    for key, patient_id in [("a", "patient-a"), ("e", "patient-e")]:
        result = _run(key, patient_id)
        for finding in result.findings:
            if finding.verdict == ClaimVerdict.VERIFIED and any(
                cr.verdict.value == "verified_span" for cr in finding.citation_results
            ):
                verified_patients.append(patient_id)
                break

    assert len(verified_patients) >= 2, verified_patients


def test_determinism_same_patient_twice_yields_identical_deterministic_output() -> None:
    """Running the same patient through `run_patient` twice with the same
    Fake Gemini + same snapshot yields identical deterministic outputs.

    Model prose (statement/rationale/etc.) is model-authored and intentionally
    NOT compared here -- only the deterministic facts/verdicts are asserted
    (normalized facts via rule_results/timeline_events, rule results, citation
    verdicts, and final claim verdicts).
    """
    result_1 = _run("a", "patient-a")
    result_2 = _run("a", "patient-a")

    assert result_1.timeline_events == result_2.timeline_events
    assert result_1.rule_results == result_2.rule_results
    assert [f.verdict for f in result_1.findings] == [f.verdict for f in result_2.findings]
    assert [[cr.verdict for cr in f.citation_results] for f in result_1.findings] == [
        [cr.verdict for cr in f.citation_results] for f in result_2.findings
    ]
    assert result_1.summary == result_2.summary


def test_failed_fhir_fetch_yields_failed_status_not_silent_empty_findings() -> None:
    """A FHIR fetch error must end the run FAILED, never a silent empty-findings success."""
    cassette = _load_cassette("a")
    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)

    result = run_patient(
        patient_bundle_ref="patient_does_not_exist.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=_model_a_client(cassette, patient_id="patient-a"),
        model_b=_model_b_client(cassette),
        clock=lambda: _NOW,
        repo=InMemoryRunRepository(),
    )

    assert result.summary.status == PatientStatus.FAILED
    assert result.error is not None
    assert result.findings == ()


def test_custom_model_a_system_instruction_overrides_the_pinned_default() -> None:
    """Spec §53, Phase C seam: a caller-supplied `model_a_system_instruction`
    is what actually reaches Model A's turn -- not the pinned
    `MODEL_A_SYSTEM_INSTRUCTION` -- which is what lets the outer
    self-improving loop's live evaluator run a CANDIDATE prompt against a
    real patient without ever mutating the pinned module constant itself.
    """
    cassette = _load_cassette("a")
    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(_DEMO_DIR)
    model_a = _model_a_client(cassette, patient_id="patient-a")
    custom_instruction = "CUSTOM TEST MODEL-A INSTRUCTION: reason carefully, cite verbatim spans."

    result = run_patient(
        patient_bundle_ref="patient_a.json",
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=model_a,
        model_b=_model_b_client(cassette),
        clock=lambda: _NOW,
        repo=InMemoryRunRepository(),
        run_id="demo-run-a-custom-instruction",
        model_a_system_instruction=custom_instruction,
    )

    assert result.error is None
    assert model_a.calls, "Model A must have been called at least once"
    assert model_a.calls[0].startswith(custom_instruction)
    assert MODEL_A_SYSTEM_INSTRUCTION not in model_a.calls[0]
