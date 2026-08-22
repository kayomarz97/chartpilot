"""Zero-network fakes for the accelerated live run's `--fake` smoke-test path.

`FakeGeminiClient` mirrors `backend/tests/support/fake_gemini.py`'s
cassette-driven fake exactly (same needle-matching `create()` contract, same
`AssertionError` on an unmatched call) but is reimplemented here rather than
imported from `tests.support` -- `scripts/` is not part of the `backend`
package and must not depend on `backend`'s test-only code to run its own
`--fake` smoke test.

`build_fake_model_clients` builds one shared `FakeGeminiClient` pair for an
entire round (every patient's Model A / Model B calls go through the same
two client instances, exactly like the real `GeminiInteractionsClient`
instances `scripts/live_round.py` builds for the live path). Every fake
claim is derived from `scripts.live_run.patients.manifest_entry` data alone
(never re-deriving a `PatientSpec`), so it always matches what is actually
in the generated bundle it will be scored against.

`build_fake_generator`/`build_fake_score_fn` are the `--fake` path for
`scripts/improve_round.py`'s outer loop: a deterministic "improvement" (a
fixed marker sentence appended to the current prompt) that a deterministic
`ScoreFn` always scores strictly higher than any value lacking that marker
-- enough to exercise the propose -> evaluate -> canary -> promote path
end to end with zero tokens, per the task's requirement.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.protocol import InteractionResult
from app.improve.evaluator import ScoreFn
from app.improve.models import Candidate, ImproveTarget, Metrics
from app.improve.proposer import Generator

__all__ = [
    "FakeGeminiClient",
    "build_fake_model_clients",
    "build_fake_generator",
    "build_fake_score_fn",
    "FAKE_IMPROVEMENT_MARKER",
]

#: The exact verbatim span present in the packaged demo evidence snapshot's
#: enalapril-class openFDA label (`app.demo_data.evidence_snapshot.json`,
#: record id below) -- copying it character-for-character is what makes the
#: "clean" fake claims below pass the real SPAN_VERIFICATION gate.
_LISINOPRIL_EVIDENCE_ID = "openfda:e81a8aca-0e7c-4a02-b596-09e4ac22c70e:adverse_reactions"
_VERBATIM_HYPERKALEMIA_SPAN = "Hyperkalemia [see Warnings and Precautions (5.6) ]"
#: Deliberately NOT a substring of the evidence record's content -- used for
#: roughly 1 in 3 medicated patients so the round's citation verified-span
#: rate is genuinely < 100%, giving the outer loop something to react to
#: (see module docstring).
_CORRUPTED_HYPERKALEMIA_SPAN = "Hyperkalemia has previously been reported with this agent"


class FakeGeminiClient:
    """Deterministic, hermetic `GeminiClient`-shaped fake (see module
    docstring) -- structurally satisfies `app.agent.protocol.GeminiClient`
    without importing it, so this module has zero dependency on `backend`."""

    def __init__(self, responses: list[tuple[str, str]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def list_models(self) -> list[str]:
        return []

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        self.calls.append(input)
        for needle, output_text in self._responses:
            if needle in input:
                return InteractionResult(
                    interaction_id=f"fake-interaction-{len(self.calls)}",
                    output_text=output_text,
                    function_calls=(),
                )
        raise AssertionError(
            f"FakeGeminiClient: no fake response matched call #{len(self.calls)} "
            f"input (first 300 chars): {input[:300]!r}"
        )


def _fake_claim(patient: dict[str, Any]) -> dict[str, Any]:
    """Build one fake Model-A claim dict (matches `app.agent.models.Claim`'s
    JSON shape) for one `scripts.live_run.patients.manifest_entry` record."""
    patient_id = patient["patient_id"]
    index = patient["index"]
    claim_id = f"claim-{patient_id}-1"
    k_value = patient["potassium_value"]

    if patient["has_k_raising_med"]:
        corrupt = index % 3 == 1
        span = _CORRUPTED_HYPERKALEMIA_SPAN if corrupt else _VERBATIM_HYPERKALEMIA_SPAN
        claim_type = "possible_concern" if patient["is_k_critical"] else "patient_specific_inference"
        severity = "critical" if patient["is_k_critical"] else "moderate"
        statement = (
            f"Patient {patient_id}'s potassium is {k_value} mmol/L while on an active "
            "ACE inhibitor, which may worsen hyperkalemia given the renal picture."
        )
        return {
            "claim_id": claim_id,
            "claim_type": claim_type,
            "statement": statement,
            "patient_evidence": [
                {"resource_type": "Observation", "resource_id": patient["potassium_obs_id"]},
                {"resource_type": "MedicationRequest", "resource_id": patient["med_id"]},
            ],
            "external_evidence": [
                {"evidence_id": _LISINOPRIL_EVIDENCE_ID, "verbatim_supporting_span": span}
            ],
            "severity": severity,
            "confidence": 0.75,
            "rationale": (
                f"Potassium {k_value} mmol/L on an active ACE inhibitor; the cited label "
                "text lists hyperkalemia as a known adverse reaction for this drug class."
            ),
            "recommended_action": "Consider a repeat potassium level and reviewing the ACE inhibitor.",
        }

    statement = (
        f"Patient {patient_id}'s most recent potassium is {k_value} mmol/L and "
        f"creatinine is {patient['creatinine_value']} mg/dL, with no active "
        "potassium-raising medication on the chart."
    )
    return {
        "claim_id": claim_id,
        "claim_type": "patient_fact",
        "statement": statement,
        "patient_evidence": [
            {"resource_type": "Observation", "resource_id": patient["potassium_obs_id"]},
            {"resource_type": "Observation", "resource_id": patient["creatinine_obs_id"]},
        ],
        "external_evidence": [],
        "severity": None,
        "confidence": 0.9,
        "rationale": "Directly restates the patient's own chart values; no external evidence needed.",
        "recommended_action": None,
    }


def build_fake_model_clients(
    manifest_patients: list[dict[str, Any]],
) -> tuple[FakeGeminiClient, FakeGeminiClient]:
    """Build one shared `(model_a, model_b)` `FakeGeminiClient` pair covering
    every patient in `manifest_patients` (`scripts.live_run.patients.
    manifest_entry` records, e.g. `manifest["patients"]`)."""
    model_a_responses: list[tuple[str, str]] = []
    model_b_responses: list[tuple[str, str]] = []

    for patient in manifest_patients:
        claim = _fake_claim(patient)
        needle_a = f"PATIENT_ID: {patient['patient_id']}"
        model_a_responses.append((needle_a, json.dumps({"claims": [claim]})))

        model_b_verdict = {
            "finding": "supported",
            "should_reject": False,
            "rationale": "fake reviewer: chart facts match, no disqualifying context present.",
            "suggested_safer_wording": None,
        }
        model_b_responses.append((claim["statement"], json.dumps(model_b_verdict)))

    return FakeGeminiClient(model_a_responses), FakeGeminiClient(model_b_responses)


# ---------------------------------------------------------------------------
# scripts/improve_round.py --fake: deterministic proposer + score_fn
# ---------------------------------------------------------------------------

#: Appended to the current prompt by `build_fake_generator`'s candidate, and
#: what `build_fake_score_fn` looks for to decide "this is the improved
#: value" -- the whole fake accept/promote path hinges on this one marker.
FAKE_IMPROVEMENT_MARKER = (
    "\n\n# FAKE-IMPROVED (scripts/live_run --fake smoke test): copy the shortest "
    "exact substring when quoting a citation span.\n"
)


def build_fake_generator(current_prompt: str) -> Generator:
    """Deterministic fake `app.improve.proposer.Generator`: always returns
    `current_prompt` plus `FAKE_IMPROVEMENT_MARKER`, ignoring the dataset
    entirely (no network, no LLM). Mirrors `LlmProposer`'s
    hardcoded-`target` safety property (never model/caller-chosen)."""

    def generate(dataset: Any, target: ImproveTarget) -> Candidate:
        del dataset, target  # deterministic fake: ignores both
        return Candidate(
            target=ImproveTarget.MODEL_A_PROMPT,
            new_value=current_prompt + FAKE_IMPROVEMENT_MARKER,
            rationale=(
                "fake --fake smoke-test candidate: appended a deterministic marker "
                "sentence so the propose/evaluate/canary/promote path can be exercised "
                "end to end with zero network calls."
            ),
        )

    return generate


def build_fake_score_fn() -> ScoreFn:
    """Deterministic fake `app.improve.evaluator.ScoreFn`: any value
    containing `FAKE_IMPROVEMENT_MARKER` scores strictly higher than any
    value that does not -- guarantees `evaluate_candidate`/`canary_compare`
    both accept the fake candidate built by `build_fake_generator`, so the
    ledger promotion path is genuinely exercised offline."""

    def score(value: str) -> Metrics:
        improved = FAKE_IMPROVEMENT_MARKER in value
        return Metrics(
            set_d_blocked=100 if improved else 50,
            set_m_caught=0,
            false_reject=0,
            clinician_agreement=1.0,
        )

    return score
