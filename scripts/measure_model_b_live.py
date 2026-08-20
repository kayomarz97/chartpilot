#!/usr/bin/env python3
"""LIVE §22.3 Model B corruption-suite measurement.

Runs the full §22 Set D / Set M corruption suite
(`app.review.corruption.build_set_d_cases` / `build_set_m_cases` /
`measure_suite`) plus a small control set of genuinely correct, uncorrupted
claims, through:

  - Set D: the REAL deterministic layer (`app.review.deterministic
    .run_deterministic_layer`) -- Model B must never even be called for a
    Set D case (measure_suite enforces this itself).
  - Set M + control: the deterministic layer first, then -- for whatever
    isn't already blocked there -- the REAL Model B
    (`GeminiInteractionsClient`, `gemini-3.5-flash`; credentials from
    `backend/.env` via `app.config.get_settings`).

The base `ClaimUnderReview` each corruption is applied to is built from demo
Patient A's own chart (`patient_a.json`) + its cassette's Model-A-authored
claim (`claim-a-1`) + the committed evidence snapshot -- the same real,
already-verified claim `tests/unit/test_pipeline_demo.py` runs Patient A
through, just re-hydrated here without going through Model A itself (Model A
is not part of what this script measures). The control set adds a few more
of the OTHER demo patients' own real, uncorrupted, VERIFIED claims (B, D, E)
for a broader false-reject sample than Patient A's claim alone would give.

Prints the resulting `SuiteReport` (Set D blocked-pre-B rate, Set M catch
rate, false-accept, false-reject vs the control set) and the §22.3 release
decision (`app.review.corruption.release_threshold_met`) -- badge vs
ADVISORY.

COSTS REAL TOKENS. Never run by `make check` / pytest -- this script makes
real Gemini API calls.

Usage:
    cd backend && uv run python ../scripts/measure_model_b_live.py
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo"
CASSETTES_DIR = DEMO_DIR / "cassettes"

#: (cassette key, patient id) for the control-set patients, in addition to
#: the Patient A claim the Set D/M corruptions are built from.
_CONTROL_PATIENTS: tuple[tuple[str, str], ...] = (
    ("b", "patient-b"),
    ("d", "patient-d"),
    ("e", "patient-e"),
)

if TYPE_CHECKING:
    from app.review.models import ClaimUnderReview


def _load_cassette(patient_key: str) -> dict[str, Any]:
    return json.loads((CASSETTES_DIR / f"patient_{patient_key}.json").read_text(encoding="utf-8"))


def _build_claim_under_review(patient_key: str, patient_id: str) -> "ClaimUnderReview":
    """Re-hydrate the real `ClaimUnderReview` for one demo patient's own
    (already Model-A-authored, cassette-recorded) first claim.

    Mirrors `app.pipeline.runner._build_claim_under_review`'s asserted-fact
    extraction exactly (that helper is module-private, so it is not
    imported directly) -- see that function's docstring for the extraction
    rationale.
    """
    from app.agent.models import Claim
    from app.fhir.client import FhirClient
    from app.fhir.transport import LocalFixtureTransport
    from app.normalize.medication import normalize_medication_order
    from app.normalize.observation import normalize_observation
    from app.normalize.units import NormalizedQuantity
    from app.review.models import (
        AssertedMedication,
        AssertedObservationValue,
        ClaimUnderReview,
        PatientFactIndex,
    )

    analyte_by_code = {
        "2823-3": "potassium",
        "6298-4": "potassium",
        "2951-2": "sodium",
        "2947-0": "sodium",
        "2160-0": "creatinine",
        "38483-4": "creatinine",
    }

    transport = LocalFixtureTransport(DEMO_DIR)
    resources = FhirClient(transport).fetch_all(f"patient_{patient_key}.json")
    observations = [
        normalize_observation(r) for r in resources if r.get("resourceType") == "Observation"
    ]
    medications = [
        normalize_medication_order(r)
        for r in resources
        if r.get("resourceType") == "MedicationRequest"
    ]
    patient_index = PatientFactIndex(
        patient_id=patient_id,
        observations={obs.id: obs for obs in observations},
        medications={med.id: med for med in medications},
    )

    cassette = _load_cassette(patient_key)
    claim = Claim.model_validate(cassette["model_a"]["claims"][0])

    asserted_observations: list[AssertedObservationValue] = []
    asserted_medications: list[AssertedMedication] = []
    for ref in claim.patient_evidence:
        if ref.resource_type == "Observation":
            obs = patient_index.observations.get(ref.resource_id)
            if obs is not None and isinstance(obs.value, NormalizedQuantity):
                asserted_observations.append(
                    AssertedObservationValue(
                        resource_id=ref.resource_id,
                        analyte=analyte_by_code.get(obs.code, obs.display or obs.code),
                        value=obs.value.value,
                        unit=obs.value.unit,
                    )
                )
            elif obs is None:
                asserted_observations.append(
                    AssertedObservationValue(
                        resource_id=ref.resource_id, analyte="unknown", value=Decimal(0), unit=""
                    )
                )
        elif ref.resource_type == "MedicationRequest":
            med = patient_index.medications.get(ref.resource_id)
            ingredient = med.medication_display if med is not None else None
            asserted_medications.append(
                AssertedMedication(
                    resource_id=ref.resource_id, ingredient=ingredient or ref.resource_id
                )
            )

    return ClaimUnderReview(
        claim=claim,
        asserted_observations=tuple(asserted_observations),
        asserted_medications=tuple(asserted_medications),
        patient_index=patient_index,
        rule_results=(),
    )


def main() -> None:
    from app.agent.gemini import GeminiInteractionsClient
    from app.config import get_settings
    from app.pipeline.demo_evidence import load_demo_snapshot
    from app.review.corruption import (
        CorruptionCase,
        CorruptionSet,
        build_set_d_cases,
        build_set_m_cases,
        measure_suite,
        release_threshold_met,
    )
    from app.review.deterministic import run_deterministic_layer
    from app.review.models import ModelBPacket, ModelBVerdict
    from app.review.reviewer import run_model_b as real_run_model_b

    settings = get_settings()
    print(f"Model B: {settings.model_b_id}")
    model_b_client = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_b_id
    )

    snapshot = load_demo_snapshot()
    base_claim = _build_claim_under_review("a", "patient-a")

    set_d_cases = build_set_d_cases(base_claim, snapshot)
    set_m_cases = build_set_m_cases(base_claim, snapshot)

    control_cases: list[CorruptionCase] = [
        CorruptionCase(
            name="control-patient-a",
            corruption_set=CorruptionSet.MODEL_ONLY,
            claim_under_review=base_claim,
            snapshot=snapshot,
        )
    ]
    for patient_key, patient_id in _CONTROL_PATIENTS:
        control_cases.append(
            CorruptionCase(
                name=f"control-{patient_id}",
                corruption_set=CorruptionSet.MODEL_ONLY,
                claim_under_review=_build_claim_under_review(patient_key, patient_id),
                snapshot=snapshot,
            )
        )

    def deterministic_runner(cur: "ClaimUnderReview", snap: Any) -> Any:
        return run_deterministic_layer(cur, snapshot=snap)

    def model_b_runner(name: str, packet: ModelBPacket) -> ModelBVerdict:
        return real_run_model_b(model_b_client, packet)

    report = measure_suite(
        set_d=set_d_cases,
        set_m=set_m_cases,
        control=control_cases,
        run_deterministic=deterministic_runner,
        run_model_b=model_b_runner,
    )

    print()
    print("=== spec §22 Model B corruption suite (LIVE) ===")
    print(
        f"Set D:    {report.set_d_blocked_pre_b}/{report.set_d_total} blocked pre-Model-B "
        "(must be 100% -- release gate requirement)"
    )
    print(
        f"Set M:    {report.set_m_caught}/{report.set_m_total} caught "
        f"(catch_rate={report.set_m_catch_rate:.1%}, false_accept={report.false_accept})"
    )
    print(f"Control:  {report.false_reject}/{report.control_total} false_reject")
    print()
    threshold_met = release_threshold_met(report)
    print(f"§22.3 release threshold met: {threshold_met}")
    print(f"decision: {'PASS badge' if threshold_met else 'ADVISORY (threshold not met)'}")


if __name__ == "__main__":
    main()
