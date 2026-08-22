"""Tests for `app.improve.proposer_llm.LlmProposer` -- the real LLM-backed
Model-A-prompt proposer. Hermetic throughout: driven entirely by
`tests.support.fake_gemini.FakeGeminiClient`, never a real Gemini call.
"""

from __future__ import annotations

import json

import pytest

from app.improve.errors import FrozenTargetError, ProposerOutputError
from app.improve.models import Candidate, Dataset, ImproveTarget, TrainingCase
from app.improve.proposer import propose_candidate
from app.improve.proposer_llm import PROPOSER_SYSTEM_INSTRUCTION, LlmProposer
from tests.support.fake_gemini import FakeGeminiClient


def _dataset_with_failures() -> Dataset:
    cases = (
        TrainingCase(
            patient_id="patient-1",
            claim_id="claim-1",
            claim_type="patient_specific_inference",
            verdict="REJECTED",
            citation_verdicts=("REJECT",),
            model_b_should_reject=False,
            revision_attempts=1,
        ),
        TrainingCase(
            patient_id="patient-1",
            claim_id="claim-2",
            claim_type="regulatory_fact",
            verdict="VERIFIED",
            citation_verdicts=("VERIFIED_SPAN",),
            model_b_should_reject=False,
            revision_attempts=0,
        ),
    )
    return Dataset(cases=cases)


def test_llm_proposer_returns_a_model_a_prompt_candidate() -> None:
    fake = FakeGeminiClient(
        [("", json.dumps({"new_value": "improved prompt text", "rationale": "tightened rules"}))]
    )
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    candidate = proposer(_dataset_with_failures(), ImproveTarget.MODEL_A_PROMPT)

    assert isinstance(candidate, Candidate)
    assert candidate.target == ImproveTarget.MODEL_A_PROMPT
    assert candidate.new_value == "improved prompt text"
    assert candidate.rationale == "tightened rules"
    assert len(fake.calls) == 1
    # The current prompt, the fixed proposer instruction, and a summary of
    # the failed cases must all reach the model turn.
    assert "current prompt text" in fake.calls[0]
    assert PROPOSER_SYSTEM_INSTRUCTION in fake.calls[0]
    assert "claim_type=patient_specific_inference" in fake.calls[0]


def test_llm_proposer_summary_reflects_an_empty_failure_museum() -> None:
    fake = FakeGeminiClient([("", json.dumps({"new_value": "x", "rationale": "y"}))])
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    proposer(Dataset(cases=()), ImproveTarget.MODEL_A_PROMPT)

    assert "no flagged/failed training cases available" in fake.calls[0]


def test_llm_proposer_raises_on_invalid_json_output() -> None:
    fake = FakeGeminiClient([("", "not valid json at all")])
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    with pytest.raises(ProposerOutputError):
        proposer(_dataset_with_failures(), ImproveTarget.MODEL_A_PROMPT)


def test_llm_proposer_raises_on_unexpected_extra_field() -> None:
    """`ProposerOutput` is `extra="forbid"` -- a model that tries to smuggle
    a `target` field (or anything else unexpected) into its structured
    output fails validation rather than being silently accepted."""
    fake = FakeGeminiClient(
        [("", json.dumps({"new_value": "x", "rationale": "y", "target": "model_a_prompt"}))]
    )
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    with pytest.raises(ProposerOutputError):
        proposer(_dataset_with_failures(), ImproveTarget.MODEL_A_PROMPT)


def test_llm_proposer_raises_on_missing_required_field() -> None:
    fake = FakeGeminiClient([("", json.dumps({"new_value": "x"}))])
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    with pytest.raises(ProposerOutputError):
        proposer(_dataset_with_failures(), ImproveTarget.MODEL_A_PROMPT)


def test_llm_proposer_works_through_propose_candidate_train_split_only() -> None:
    fake = FakeGeminiClient([("", json.dumps({"new_value": "improved", "rationale": "r"}))])
    proposer = LlmProposer(fake, current_prompt="current prompt text")

    candidate = propose_candidate(
        _dataset_with_failures(), target=ImproveTarget.MODEL_A_PROMPT, generate=proposer
    )

    assert candidate.target == ImproveTarget.MODEL_A_PROMPT
    assert candidate.new_value == "improved"


def test_propose_candidate_still_refuses_a_generator_that_escapes_to_a_frozen_target() -> None:
    """Defense in depth for the `Generator` protocol `LlmProposer` also
    implements: `LlmProposer` itself CANNOT return a non-`MODEL_A_PROMPT`
    target (it is hardcoded in code, never parsed from model output -- see
    `LlmProposer.__call__`'s docstring), so this uses a minimal stand-in
    generator to prove `propose_candidate`'s second guard is
    generator-agnostic, not specific to any one implementation."""

    def escaping_generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate.model_construct(
            target="k_high_risk_001", new_value="malicious", rationale="escape attempt"
        )

    with pytest.raises(FrozenTargetError):
        propose_candidate(
            _dataset_with_failures(),
            target=ImproveTarget.MODEL_A_PROMPT,
            generate=escaping_generate,
        )
