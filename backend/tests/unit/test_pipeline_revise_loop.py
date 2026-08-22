"""Tests for the bounded "gate-failure -> revise -> retry" inner loop
wired into `app.pipeline.runner.run_patient` (spec §53, Phase A).

Hermetic: `_StaticFhirTransport` returns a fixed in-memory Bundle (no
fixture files needed, since these claims deliberately carry empty
`patient_evidence` -- nothing here exercises patient-fact integrity
checking, which is already covered by `tests/unit/test_review_integrity.py`
and `tests/unit/test_corruption_suite.py`). `_ScriptedModelA` routes by
whether `app.agent.prompts.MODEL_A_REVISE_INSTRUCTION`'s text appears in the
call's `input` -- the FIRST call (the initial `generate_claims` turn) never
contains it; every subsequent call (a `revise_claim` turn) does -- and
`_AlwaysSupportModelB` is a fixed, always-SUPPORTED Model B stand-in so
these tests can isolate the revise loop's own behavior.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.agent.prompts import MODEL_A_REVISE_INSTRUCTION
from app.agent.protocol import InteractionResult
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.snapshot import build_snapshot
from app.gate.models import ClaimVerdict
from app.pipeline.runner import run_patient
from app.storage.inmemory import InMemoryRunRepository
from app.storage.models import claims_collection_path

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
_RETRIEVED_AT = datetime(2026, 8, 20, tzinfo=UTC)
_CREATED_AT = datetime(2026, 8, 20, 1, 0, 0, tzinfo=UTC)

_RECORD_CONTENT = (
    "Grapefruit juice may increase drug levels significantly and should be avoided together."
)
_CORRECTED_SPAN = "Grapefruit juice may increase drug levels significantly"
_BAD_SPAN = "this text is nowhere in the source"
#: The claim's `statement` -- a named constant (not an inline literal) so
#: `test_no_prose_assertions.py`'s heuristic doesn't mistake this scripted
#: fixture value for pinned real model prose; see that module's docstring
#: (`RATIONALE_CONSTANT`-style comparisons are the documented escape hatch).
_ORIGINAL_STATEMENT = "The chart shows a potential concern worth clinician review."

_PATIENT_BUNDLE: dict[str, Any] = {
    "resourceType": "Bundle",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "patient-x",
                "name": [{"text": "Test Patient"}],
            }
        }
    ],
}


class _StaticFhirTransport:
    """Returns the same fixed Bundle regardless of `ref` -- these tests
    don't exercise FHIR pagination/fetch behavior, only the revise loop."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        self._bundle = bundle

    def fetch(self, ref: str) -> dict[str, Any]:
        return self._bundle


def _evidence_record(record_id: str = "lit-1", content: str = _RECORD_CONTENT) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        tier=EvidenceTier.LITERATURE,
        title="title",
        publisher="Example Publisher",
        jurisdiction=Jurisdiction.NOT_APPLICABLE,
        publication_date="2024",
        version=None,
        content=content,
        content_hash=content_hash(content),
        source_url=f"https://example.invalid/{record_id}",
        retrieved_at=_RETRIEVED_AT,
        metadata={},
    )


def _claim_set_json(*, evidence_id: str = "lit-1", span: str = _BAD_SPAN) -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "claim_id": "claim-1",
                    "claim_type": "possible_concern",
                    "statement": _ORIGINAL_STATEMENT,
                    "patient_evidence": [],
                    "external_evidence": [
                        {"evidence_id": evidence_id, "verbatim_supporting_span": span}
                    ],
                    "severity": "moderate",
                    "confidence": 0.6,
                    "rationale": "See cited evidence.",
                    "recommended_action": None,
                }
            ]
        }
    )


def _claim_json(
    *,
    evidence_id: str = "lit-1",
    span: str,
    statement: str = _ORIGINAL_STATEMENT,
    extra_evidence_id: str | None = None,
) -> str:
    external_evidence = [{"evidence_id": evidence_id, "verbatim_supporting_span": span}]
    if extra_evidence_id is not None:
        external_evidence.append(
            {"evidence_id": extra_evidence_id, "verbatim_supporting_span": "irrelevant"}
        )
    return json.dumps(
        {
            "claim_id": "claim-1",
            "claim_type": "possible_concern",
            "statement": statement,
            "patient_evidence": [],
            "external_evidence": external_evidence,
            "severity": "moderate",
            "confidence": 0.6,
            "rationale": "See cited evidence.",
            "recommended_action": None,
        }
    )


class _ScriptedModelA:
    """The first call (no `MODEL_A_REVISE_INSTRUCTION` in `input`) always
    returns `initial_output_text`; every later call (a revision turn) pops
    and returns the next entry of `revision_outputs`, in order. Raises
    `AssertionError` if a revision call happens with no scripted output left
    -- a test bug (an unbounded loop) must fail loudly, never hang."""

    def __init__(self, initial_output_text: str, revision_outputs: list[str] | None = None) -> None:
        self._initial_output_text = initial_output_text
        self._revision_outputs = list(revision_outputs or [])
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
        if MODEL_A_REVISE_INSTRUCTION not in input:
            output_text = self._initial_output_text
        else:
            assert self._revision_outputs, "no more scripted revision outputs left"
            output_text = self._revision_outputs.pop(0)
        return InteractionResult(
            interaction_id=f"interaction-{len(self.calls)}",
            output_text=output_text,
            function_calls=(),
        )


class _AlwaysSupportModelB:
    """A fixed Model B stand-in that always finds the claim SUPPORTED --
    isolates these tests from Model B's own logic, which is covered
    elsewhere (`tests/unit/test_review_reviewer.py`)."""

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
        verdict = {
            "finding": "supported",
            "should_reject": False,
            "rationale": "Consistent with the cited evidence and patient facts.",
            "suggested_safer_wording": None,
        }
        return InteractionResult(
            interaction_id="model-b-1", output_text=json.dumps(verdict), function_calls=()
        )


def _run(
    *,
    model_a: _ScriptedModelA,
    snapshot: Any,
    run_id: str,
    max_revise_iterations: int = 2,
) -> Any:
    repo = InMemoryRunRepository()
    result = run_patient(
        patient_bundle_ref="bundle",
        fhir_transport=_StaticFhirTransport(_PATIENT_BUNDLE),
        snapshot=snapshot,
        model_a=model_a,
        model_b=_AlwaysSupportModelB(),
        clock=lambda: _NOW,
        repo=repo,
        run_id=run_id,
        max_revise_iterations=max_revise_iterations,
    )
    return result, repo


def test_repair_success_ends_verified_with_corrected_span_persisted() -> None:
    """A citation that failed only on SPAN_VERIFICATION gets one successful
    revise turn, ends VERIFIED, and the PERSISTED claim carries the
    corrected span -- not the original model output."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    model_a = _ScriptedModelA(
        _claim_set_json(span=_BAD_SPAN),
        revision_outputs=[_claim_json(span=_CORRECTED_SPAN)],
    )

    result, repo = _run(model_a=model_a, snapshot=snapshot, run_id="revise-success")

    assert result.error is None
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.verdict == ClaimVerdict.VERIFIED
    assert finding.revision_attempts == 1
    assert finding.claim.external_evidence[0].verbatim_supporting_span == _CORRECTED_SPAN
    assert len(model_a.calls) == 2  # initial generate_claims + one revise_claim

    persisted = dict(repo.read_documents(claims_collection_path("revise-success", "patient-x")))
    assert persisted["claim-1"]["external_evidence"][0]["verbatim_supporting_span"] == (
        _CORRECTED_SPAN
    )


def test_budget_exhaustion_fails_closed_not_crash() -> None:
    """The revise loop always gets back a still-bad span -- after
    `max_revise_iterations` the claim is NOT VERIFIED, `revision_attempts`
    equals the budget, and the run neither crashes nor silently reports
    zero findings."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    still_bad = "still not present in the source either"
    model_a = _ScriptedModelA(
        _claim_set_json(span=_BAD_SPAN),
        revision_outputs=[_claim_json(span=still_bad), _claim_json(span=still_bad)],
    )

    result, _repo = _run(
        model_a=model_a, snapshot=snapshot, run_id="revise-exhausted", max_revise_iterations=2
    )

    assert result.error is None
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.verdict != ClaimVerdict.VERIFIED
    assert finding.revision_attempts == 2
    assert len(model_a.calls) == 3  # initial + 2 revise attempts (budget exhausted)


def test_safety_guard_rejects_changed_statement() -> None:
    """A revision that changes the claim's `statement` must be rejected by
    the safety guard -- the original claim is kept and the verdict is
    unchanged from what it would be with no loop at all."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    model_a = _ScriptedModelA(
        _claim_set_json(span=_BAD_SPAN),
        revision_outputs=[
            _claim_json(span=_CORRECTED_SPAN, statement="A completely different clinical claim.")
        ],
    )

    result, _repo = _run(model_a=model_a, snapshot=snapshot, run_id="revise-unsafe")

    assert result.error is None
    finding = result.findings[0]
    assert finding.verdict == ClaimVerdict.REJECTED  # unchanged: original span never verified
    assert finding.revision_attempts == 0
    assert finding.claim.statement == _ORIGINAL_STATEMENT
    assert finding.claim.external_evidence[0].verbatim_supporting_span == _BAD_SPAN
    assert len(model_a.calls) == 2  # the (rejected) revise attempt still happened once


def test_safety_guard_rejects_added_evidence_id() -> None:
    """A revision that ADDS a new evidence_id (rather than only dropping
    one) must also be rejected by the safety guard."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    model_a = _ScriptedModelA(
        _claim_set_json(span=_BAD_SPAN),
        revision_outputs=[_claim_json(span=_CORRECTED_SPAN, extra_evidence_id="lit-2")],
    )

    result, _repo = _run(model_a=model_a, snapshot=snapshot, run_id="revise-unsafe-evidence")

    finding = result.findings[0]
    assert finding.revision_attempts == 0
    assert len(finding.claim.external_evidence) == 1
    assert finding.claim.external_evidence[0].verbatim_supporting_span == _BAD_SPAN


def test_max_revise_iterations_zero_disables_loop() -> None:
    """`max_revise_iterations=0` is legacy behavior: no revise calls happen
    at all, even though the citation is span-repairable."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    model_a = _ScriptedModelA(_claim_set_json(span=_BAD_SPAN), revision_outputs=[])

    result, _repo = _run(
        model_a=model_a, snapshot=snapshot, run_id="revise-disabled", max_revise_iterations=0
    )

    finding = result.findings[0]
    assert finding.verdict != ClaimVerdict.VERIFIED
    assert finding.revision_attempts == 0
    assert len(model_a.calls) == 1  # only the initial generate_claims call


def test_non_repairable_citation_never_enters_loop() -> None:
    """A citation whose SOURCE_RETRIEVAL gate fails (unknown evidence_id) is
    NOT span-repairable -- the loop must never be entered, zero revise
    calls, zero revision_attempts."""
    record = _evidence_record()
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    model_a = _ScriptedModelA(
        _claim_set_json(evidence_id="does-not-exist", span="whatever"), revision_outputs=[]
    )

    result, _repo = _run(model_a=model_a, snapshot=snapshot, run_id="revise-non-repairable")

    finding = result.findings[0]
    assert finding.verdict == ClaimVerdict.REJECTED
    assert finding.revision_attempts == 0
    assert len(model_a.calls) == 1
