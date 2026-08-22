"""Tests for `app.agent.revise` (spec §53, Phase A: the bounded
"gate-failure -> revise -> retry" loop's hint-building and model-call
plumbing, in isolation from the pipeline wiring in
`test_pipeline_revise_loop.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.agent.errors import StructuredOutputError
from app.agent.models import Claim, ClaimType, ExternalEvidenceRef
from app.agent.prompts import MODEL_A_REVISE_INSTRUCTION
from app.agent.protocol import InteractionResult
from app.agent.revise import build_revision_hint, revise_claim
from app.citation.verifier import verify_citation
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceTier, Jurisdiction
from app.evidence.snapshot import build_snapshot

_RETRIEVED_AT = datetime(2026, 8, 20, tzinfo=UTC)
_CREATED_AT = datetime(2026, 8, 20, 1, 0, 0, tzinfo=UTC)


def _record(record_id: str, text: str) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        tier=EvidenceTier.LITERATURE,
        title=f"title-{record_id}",
        publisher="Example Publisher",
        jurisdiction=Jurisdiction.NOT_APPLICABLE,
        publication_date="2024",
        version=None,
        content=text,
        content_hash=content_hash(text),
        source_url=f"https://example.invalid/{record_id}",
        retrieved_at=_RETRIEVED_AT,
        metadata={},
    )


def _claim(*, external_evidence: list[ExternalEvidenceRef]) -> Claim:
    return Claim(
        claim_id="claim-1",
        claim_type=ClaimType.PATIENT_FACT,
        statement="The patient's chart shows a stable trend.",
        patient_evidence=[],
        external_evidence=external_evidence,
        severity=None,
        confidence=0.5,
        rationale="Trend is stable across available readings.",
        recommended_action=None,
    )


def test_build_revision_hint_returns_none_when_nothing_repairable() -> None:
    """A citation set with only a fully-VERIFIED_SPAN result has nothing to
    repair -- `build_revision_hint` must return `None`."""
    record = _record("lit-1", "Grapefruit juice may increase drug levels.")
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    good_ref = ExternalEvidenceRef(
        evidence_id="lit-1", verbatim_supporting_span="Grapefruit juice may increase drug levels"
    )
    citation_results = (
        verify_citation(good_ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT),
    )
    claim = _claim(external_evidence=[good_ref])

    hint = build_revision_hint(claim, citation_results, snapshot)

    assert hint is None


def test_build_revision_hint_includes_source_content_for_repairable_citation() -> None:
    """A REJECT verdict caused purely by an unmatched span (every other gate
    passed) is span-repairable -- the hint must name the evidence_id, the
    rejected span, and the FULL source content, and must NOT mention an
    unrelated citation that already fully verified."""
    rejected_record = _record("lit-1", "Grapefruit juice may increase drug levels significantly.")
    verified_record = _record("lit-2", "Take with food to reduce stomach upset.")
    snapshot = build_snapshot([rejected_record, verified_record], created_at=_CREATED_AT)

    bad_ref = ExternalEvidenceRef(
        evidence_id="lit-1", verbatim_supporting_span="this text is nowhere in the source"
    )
    good_ref = ExternalEvidenceRef(
        evidence_id="lit-2", verbatim_supporting_span="Take with food to reduce stomach upset"
    )
    citation_results = (
        verify_citation(bad_ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT),
        verify_citation(good_ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT),
    )
    claim = _claim(external_evidence=[bad_ref, good_ref])

    hint = build_revision_hint(claim, citation_results, snapshot)

    assert hint is not None
    assert "lit-1" in hint
    assert bad_ref.verbatim_supporting_span in hint
    assert rejected_record.content in hint
    # The already-verified citation's evidence_id/content must not appear --
    # only span-repairable citations are described.
    assert "lit-2" not in hint
    assert verified_record.content not in hint


def test_build_revision_hint_describes_ambiguous_span() -> None:
    """A FLAG_FOR_REVIEW (ambiguous, >1 occurrence) citation is also
    span-repairable and must be described distinctly from a not-found one."""
    record = _record("lit-1", "Take with food. Take with food, not on an empty stomach.")
    snapshot = build_snapshot([record], created_at=_CREATED_AT)
    ambiguous_ref = ExternalEvidenceRef(
        evidence_id="lit-1", verbatim_supporting_span="Take with food"
    )
    citation_results = (
        verify_citation(ambiguous_ref, snapshot=snapshot, claim_type=ClaimType.PATIENT_FACT),
    )
    claim = _claim(external_evidence=[ambiguous_ref])

    hint = build_revision_hint(claim, citation_results, snapshot)

    assert hint is not None
    assert "AMBIGUOUS" in hint
    assert record.content in hint


class _FakeReviseClient:
    """A minimal `GeminiClient` fake that always returns fixed output_text,
    mirroring `_FakeClaimsClient` in `test_agent_claims.py`."""

    def __init__(self, output_text: str) -> None:
        self._output_text = output_text
        self.last_call_kwargs: dict[str, Any] | None = None

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
        self.last_call_kwargs = {
            "input": input,
            "response_schema": response_schema,
            "store": store,
        }
        return InteractionResult(
            interaction_id="interaction-1", output_text=self._output_text, function_calls=()
        )


def test_revise_claim_calls_client_with_instruction_hint_and_original_claim() -> None:
    """`revise_claim` must wire `MODEL_A_REVISE_INSTRUCTION`, the original
    claim JSON, and the hint into the call, and use `Claim.model_json_schema()`
    (not `ClaimSet`'s) as the response schema."""
    original = _claim(
        external_evidence=[
            ExternalEvidenceRef(evidence_id="lit-1", verbatim_supporting_span="bad span")
        ]
    )
    corrected = original.model_copy(
        update={
            "external_evidence": [
                ExternalEvidenceRef(evidence_id="lit-1", verbatim_supporting_span="corrected span")
            ]
        }
    )
    fake_client = _FakeReviseClient(corrected.model_dump_json())

    result = revise_claim(fake_client, claim=original, revision_hint="HINT TEXT HERE")

    assert result == corrected
    assert fake_client.last_call_kwargs is not None
    call_input = fake_client.last_call_kwargs["input"]
    assert MODEL_A_REVISE_INSTRUCTION in call_input
    assert "HINT TEXT HERE" in call_input
    assert original.claim_id in call_input
    assert fake_client.last_call_kwargs["response_schema"] == Claim.model_json_schema()


def test_revise_claim_raises_structured_output_error_on_invalid_output() -> None:
    """Malformed/invalid model output must fail closed as
    `StructuredOutputError`, never be coerced or silently accepted."""
    fake_client = _FakeReviseClient("not valid json at all")
    claim = _claim(external_evidence=[])

    with pytest.raises(StructuredOutputError):
        revise_claim(fake_client, claim=claim, revision_hint="HINT")
