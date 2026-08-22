"""Tests for `app.improve.proposer`: the hard tier guard + `propose_candidate`."""

from __future__ import annotations

import pytest

from app.improve.errors import FrozenTargetError
from app.improve.models import Candidate, Dataset, ImproveTarget, TrainingCase
from app.improve.proposer import AUTO_TIER_TARGETS, assert_target_allowed, propose_candidate


def test_auto_tier_targets_matches_improve_target_enum() -> None:
    assert AUTO_TIER_TARGETS == {"model_a_prompt", "evidence_ranking"}


@pytest.mark.parametrize("target", list(ImproveTarget))
def test_assert_target_allowed_accepts_every_auto_target(target: ImproveTarget) -> None:
    assert_target_allowed(target.value)  # must not raise


@pytest.mark.parametrize(
    "target",
    [
        "k_high_risk_001",
        "finalize_claim_verdict",
        "normalize_observation",
        "validity_metrics",
    ],
)
def test_assert_target_allowed_rejects_known_frozen_names(target: str) -> None:
    with pytest.raises(FrozenTargetError):
        assert_target_allowed(target)


def test_assert_target_allowed_default_denies_unknown_target() -> None:
    """A target this guard has never heard of (not in AUTO, not in the
    documented FROZEN list either) must still be refused -- default-deny."""
    with pytest.raises(FrozenTargetError):
        assert_target_allowed("some_future_component_nobody_documented_yet")


def _empty_dataset() -> Dataset:
    return Dataset(cases=())


def test_propose_candidate_calls_generate_with_the_train_split_only() -> None:
    cases = tuple(
        TrainingCase(
            patient_id="patient-1",
            claim_id=f"claim-{i}",
            claim_type="patient_fact",
            verdict="VERIFIED",
            citation_verdicts=("VERIFIED_SPAN",),
            model_b_should_reject=False,
            revision_attempts=0,
        )
        for i in range(20)
    )
    dataset = Dataset(cases=cases)
    expected_train, expected_holdout = dataset.split()
    assert expected_holdout.cases, "fixture must exercise a non-empty holdout"

    seen: list[Dataset] = []

    def fake_generate(train: Dataset, target: ImproveTarget) -> Candidate:
        seen.append(train)
        return Candidate(target=target, new_value="new prompt text", rationale="test")

    propose_candidate(dataset, target=ImproveTarget.MODEL_A_PROMPT, generate=fake_generate)

    assert len(seen) == 1
    assert seen[0].cases == expected_train.cases
    # The holdout must never leak into what the generator saw.
    holdout_ids = {c.claim_id for c in expected_holdout.cases}
    train_ids = {c.claim_id for c in seen[0].cases}
    assert holdout_ids.isdisjoint(train_ids)


def test_propose_candidate_raises_frozen_target_error_for_a_frozen_target() -> None:
    def fake_generate(train: Dataset, target: ImproveTarget) -> Candidate:
        raise AssertionError("generate must never be called for a disallowed target")

    with pytest.raises(FrozenTargetError):
        propose_candidate(
            _empty_dataset(),
            target="k_high_risk_001",  # type: ignore[arg-type]
            generate=fake_generate,
        )


def test_propose_candidate_raises_when_generator_escapes_to_a_frozen_target() -> None:
    """A generator that (buggily or adversarially) returns a `Candidate`
    whose `target` was never validated as AUTO-tier (constructed via
    `model_construct`, bypassing normal enum validation) must be refused by
    the SECOND guard call, not silently passed through."""

    def escaping_generate(train: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate.model_construct(
            target="k_high_risk_001", new_value="malicious", rationale="escape attempt"
        )

    with pytest.raises(FrozenTargetError):
        propose_candidate(
            _empty_dataset(), target=ImproveTarget.MODEL_A_PROMPT, generate=escaping_generate
        )
