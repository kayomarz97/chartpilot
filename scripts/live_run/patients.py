"""Deterministic synthetic-patient generation for the accelerated live run.

`generate_patient(index)` builds one FHIR `Bundle` of the exact shape
`app.fhir.client.FhirClient.fetch_all` / `app.fhir.transport.
LocalFixtureTransport` already read (mirrors `backend/tests/fixtures/demo/
patient_a.json`: a `searchset` Bundle of `entry[].resource` objects).

**Vocabulary is deliberately narrow and fixed**, matching the ONLY
drug/analyte combination the packaged demo evidence snapshot
(`backend/app/demo_data/evidence_snapshot.json`) has evidence for: an ACE
inhibitor (lisinopril -- `app.rules.medication_classes`'s `ACE_INHIBITOR`
class, matched by the openFDA enalapril-class label's hyperkalemia adverse
reaction span) causing/worsening hyperkalemia in a patient with declining
renal function. Every generated patient varies only the VALUES and
COMBINATIONS within that vocabulary (potassium level, whether the
potassium-raising medication is present, creatinine/eGFR trajectory,
age/sex) -- never the vocabulary itself -- so every citation a live Model A
run produces has a real chance to verify against real evidence, per this
phase's citation-signal requirement (see the calling scripts' docstrings).

Deterministic from `index` alone: no RNG, no wall-clock read anywhere in
this module (`datetime.now()` is never called here) -- the same `index`
always produces the byte-identical bundle, across processes and runs. The
caller (`scripts/gen_patients.py`) computes `index = round * 100 + i` so
patients are guaranteed distinct across every round of this live run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["PatientSpec", "patient_spec", "generate_patient", "manifest_entry", "build_manifest"]

#: The critical potassium band `app.rules.potassium.KHighRiskConfig.
#: critical_mmol_l` is pinned to in `rules.toml` (see ARCHITECTURE.md) --
#: duplicated here as a plain float (not imported from `app.rules`) so this
#: module has zero dependency on the `backend` package, matching the rest of
#: `scripts/live_run`.
_K_CRITICAL_MMOL_L = 6.0

#: Cycles through 8 potassium values spanning normal -> critical (>=6.0),
#: mmol/L, matching `patient_a.json`'s reference range (low 3.5 / high 5.1)
#: and the K_HIGH_RISK_001 rule's high/critical bands (5.5 / 6.0). 3 of the 8
#: steps (6.0, 6.5, 7.0) are at/above critical, per the task's "some >=6.0
#: critical" requirement.
_POTASSIUM_STEPS_MMOL_L: tuple[float, ...] = (3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0)

#: Cycles through 10 creatinine values, mg/dL, spanning normal (0.7) through
#: markedly impaired (3.0) -- feeds `app.validation.metrics.EGFR_METRIC_ID`'s
#: CKD-EPI 2021 calculation via `app.pipeline.runner._evaluate_validity_metrics`.
_CREATININE_STEPS_MG_DL: tuple[float, ...] = (0.7, 0.9, 1.1, 1.3, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0)

_GIVEN_NAMES_MALE: tuple[str, ...] = (
    "James", "Robert", "John", "Michael", "David",
    "William", "Richard", "Joseph", "Thomas", "Charles",
)
_GIVEN_NAMES_FEMALE: tuple[str, ...] = (
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth",
    "Barbara", "Susan", "Jessica", "Sarah", "Karen",
)
_FAMILY_NAMES: tuple[str, ...] = (
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
)

#: Reference range shared with `patient_a.json` -- keeps
#: `app.rules.abnormality.assess_abnormality`'s reference-range basis
#: consistent with the configured K_HIGH_RISK_001 thresholds (never in
#: §29.2 conflict for the values this module generates).
_K_REFERENCE_RANGE = {"low": 3.5, "high": 5.1}
_CREATININE_REFERENCE_RANGE = {"low": 0.6, "high": 1.3}

_LISINOPRIL_DISPLAY = "Lisinopril 10 MG Oral Tablet"


@dataclass(frozen=True)
class PatientSpec:
    """Every deterministic fact about one generated patient, derived purely
    from `index` -- the single source of truth `generate_patient` (bundle
    building) and `scripts.live_run.fake_gemini` (fake-claim building) both
    read, so a `--fake` Model-A response always matches what is actually in
    the generated bundle."""

    index: int
    patient_id: str
    given_name: str
    family_name: str
    gender: str
    birth_date: str
    age_years: int
    potassium_value: float
    potassium_obs_id: str
    potassium_effective: str
    creatinine_value: float
    creatinine_obs_id: str
    creatinine_effective: str
    has_k_raising_med: bool
    med_id: str | None
    med_display: str | None
    is_k_critical: bool


def patient_spec(index: int) -> PatientSpec:
    """Derive the full deterministic `PatientSpec` for `index`.

    Pure function of `index`: no RNG, no clock. Every field cycles through a
    fixed-size table keyed by `index % len(table)` (or a simple linear
    formula), so the same `index` always yields the same spec.
    """
    patient_id = f"patient-synth-{index}"
    is_male = index % 2 == 0
    gender = "male" if is_male else "female"
    given_pool = _GIVEN_NAMES_MALE if is_male else _GIVEN_NAMES_FEMALE
    given_name = given_pool[index % len(given_pool)]
    family_name = _FAMILY_NAMES[(index // len(given_pool)) % len(_FAMILY_NAMES)]

    age_years = 35 + (index % 50)  # 35..84
    birth_year = 2026 - age_years
    birth_month = (index % 12) + 1
    birth_day = (index % 28) + 1
    birth_date = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"

    potassium_value = _POTASSIUM_STEPS_MMOL_L[index % len(_POTASSIUM_STEPS_MMOL_L)]
    creatinine_value = _CREATININE_STEPS_MG_DL[index % len(_CREATININE_STEPS_MG_DL)]

    # A fixed-but-varying observation date: never wall-clock-derived (no
    # `datetime.now()`), just an index-driven day-of-month within a pinned
    # month, so distinct patients don't all carry an identical timestamp.
    obs_month = ((index // 28) % 12) + 1
    obs_day = (index % 28) + 1
    effective = f"2026-{obs_month:02d}-{obs_day:02d}T09:00:00+00:00"

    has_k_raising_med = index % 3 != 0  # ~2/3 of patients are on the ACE inhibitor
    med_id = f"med-{patient_id}-1" if has_k_raising_med else None
    med_display = _LISINOPRIL_DISPLAY if has_k_raising_med else None

    return PatientSpec(
        index=index,
        patient_id=patient_id,
        given_name=given_name,
        family_name=family_name,
        gender=gender,
        birth_date=birth_date,
        age_years=age_years,
        potassium_value=potassium_value,
        potassium_obs_id=f"obs-{patient_id}-k",
        potassium_effective=effective,
        creatinine_value=creatinine_value,
        creatinine_obs_id=f"obs-{patient_id}-creat",
        creatinine_effective=effective,
        has_k_raising_med=has_k_raising_med,
        med_id=med_id,
        med_display=med_display,
        is_k_critical=potassium_value >= _K_CRITICAL_MMOL_L,
    )


def _observation_entry(
    *,
    obs_id: str,
    patient_id: str,
    loinc_code: str,
    loinc_display: str,
    text: str,
    value: float,
    unit: str,
    effective: str,
    reference_range: dict[str, float],
) -> dict[str, Any]:
    return {
        "fullUrl": f"Observation/{obs_id}",
        "resource": {
            "resourceType": "Observation",
            "id": obs_id,
            "status": "final",
            "code": {
                "coding": [
                    {"system": "http://loinc.org", "code": loinc_code, "display": loinc_display}
                ],
                "text": text,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": effective,
            "issued": effective,
            "valueQuantity": {
                "value": value,
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": unit,
            },
            "referenceRange": [
                {
                    "low": {"value": reference_range["low"], "unit": unit},
                    "high": {"value": reference_range["high"], "unit": unit},
                }
            ],
        },
    }


def generate_patient(index: int) -> dict[str, Any]:
    """Build one FHIR `searchset` `Bundle` for `index` (same shape
    `LocalFixtureTransport`/`FhirClient.fetch_all` read -- see module
    docstring for the vocabulary constraint and determinism guarantee)."""
    spec = patient_spec(index)
    filename = f"{spec.patient_id}.json"

    entries: list[dict[str, Any]] = [
        {
            "fullUrl": f"Patient/{spec.patient_id}",
            "resource": {
                "resourceType": "Patient",
                "id": spec.patient_id,
                "name": [{"family": spec.family_name, "given": [spec.given_name]}],
                "gender": spec.gender,
                "birthDate": spec.birth_date,
            },
        },
        _observation_entry(
            obs_id=spec.potassium_obs_id,
            patient_id=spec.patient_id,
            loinc_code="2823-3",
            loinc_display="Potassium [Moles/volume] in Serum or Plasma",
            text="Potassium",
            value=spec.potassium_value,
            unit="mmol/L",
            effective=spec.potassium_effective,
            reference_range=_K_REFERENCE_RANGE,
        ),
        _observation_entry(
            obs_id=spec.creatinine_obs_id,
            patient_id=spec.patient_id,
            loinc_code="2160-0",
            loinc_display="Creatinine [Mass/volume] in Serum or Plasma",
            text="Creatinine",
            value=spec.creatinine_value,
            unit="mg/dL",
            effective=spec.creatinine_effective,
            reference_range=_CREATININE_REFERENCE_RANGE,
        ),
        {
            "fullUrl": f"Condition/cond-{spec.patient_id}-htn",
            "resource": {
                "resourceType": "Condition",
                "id": f"cond-{spec.patient_id}-htn",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "verificationStatus": {"coding": [{"code": "confirmed"}]},
                "code": {"text": "Essential hypertension"},
                "subject": {"reference": f"Patient/{spec.patient_id}"},
                "recordedDate": "2020-01-10",
            },
        },
    ]

    if spec.has_k_raising_med:
        assert spec.med_id is not None  # narrowed for mypy-style clarity
        entries.append(
            {
                "fullUrl": f"MedicationRequest/{spec.med_id}",
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": spec.med_id,
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {"text": spec.med_display},
                    "subject": {"reference": f"Patient/{spec.patient_id}"},
                    "authoredOn": "2025-06-01T00:00:00+00:00",
                },
            }
        )

    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "link": [{"relation": "self", "url": filename}],
        "entry": entries,
    }


def manifest_entry(spec: PatientSpec) -> dict[str, Any]:
    """The JSON-serializable manifest record for one patient -- everything
    `scripts/live_round.py`'s `--fake` mode needs to build a matching fake
    Model-A claim without re-deriving `PatientSpec` itself."""
    return {
        "index": spec.index,
        "patient_id": spec.patient_id,
        "bundle_file": f"{spec.patient_id}.json",
        "gender": spec.gender,
        "age_years": spec.age_years,
        "potassium_value": spec.potassium_value,
        "potassium_obs_id": spec.potassium_obs_id,
        "creatinine_value": spec.creatinine_value,
        "creatinine_obs_id": spec.creatinine_obs_id,
        "has_k_raising_med": spec.has_k_raising_med,
        "med_id": spec.med_id,
        "med_display": spec.med_display,
        "is_k_critical": spec.is_k_critical,
    }


def build_manifest(round_num: int, count: int) -> dict[str, Any]:
    """Build the full round manifest (pure, no I/O): `round_num * 100 + i`
    for `i in range(count)`, per the task's cross-round-distinctness rule."""
    patients = [manifest_entry(patient_spec(round_num * 100 + i)) for i in range(count)]
    return {"round": round_num, "count": count, "patients": patients}
