"""End-to-end tests for `app.improve.cycle.run_improvement_cycle` with fakes
-- no LLM, no network, ledger always backed by pytest `tmp_path`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.improve.cycle import run_improvement_cycle
from app.improve.models import Candidate, Dataset, ImproveTarget, Metrics
from app.improve.promote import PromotionLedger

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _presentation(patient_id: str, claim_ids: list[str]) -> dict[str, object]:
    return {
        "patientId": patient_id,
        "findings": [
            {
                "claimId": claim_id,
                "claimType": "PATIENT_FACT",
                "verdict": "VERIFIED",
                "revisionAttempts": 0,
                "externalEvidence": [],
            }
            for claim_id in claim_ids
        ],
    }


def _improving_score_fn(value: str) -> Metrics:
    caught = 8 if value == "better prompt" else 7
    return Metrics(set_d_blocked=7, set_m_caught=caught, false_reject=0, clinician_agreement=1.0)


def _tying_score_fn(value: str) -> Metrics:
    return Metrics(set_d_blocked=7, set_m_caught=7, false_reject=0, clinician_agreement=1.0)


def test_accepted_candidate_promotes_to_the_ledger(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="better prompt", rationale="proposed")

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=_improving_score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is True
    assert report.promotion is not None
    assert report.promotion.version == "v1"
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "better prompt"


def test_rejected_candidate_leaves_active_unchanged(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "already active", version="v0", rationale="seed", now=_NOW
    )

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="no better", rationale="proposed")

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=_tying_score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is False
    assert report.promotion is None
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "already active"


def test_exception_in_propose_yields_a_rejected_report_and_never_raises(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)

    def broken_generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        raise RuntimeError("generator blew up")

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=broken_generate,
        score_fn=_improving_score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is False
    assert report.promotion is None
    assert report.evaluation is None
    assert "generator blew up" in report.detail
    assert ledger.active(ImproveTarget.MODEL_A_PROMPT) is None


def test_exception_in_score_fn_yields_a_rejected_report_and_never_raises(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="candidate", rationale="proposed")

    def broken_score_fn(value: str) -> Metrics:
        raise RuntimeError("scoring blew up")

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=broken_score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is False
    assert report.promotion is None
    assert "scoring blew up" in report.detail
    assert ledger.active(ImproveTarget.MODEL_A_PROMPT) is None


def test_exception_during_promotion_yields_a_rejected_report_and_never_raises(
    tmp_path: Path,
) -> None:
    ledger = PromotionLedger(tmp_path)

    def generate(dataset: Dataset, target: ImproveTarget) -> Candidate:
        return Candidate(target=target, new_value="better prompt", rationale="proposed")

    def broken_promote(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    # Monkeypatch the ledger instance's promote method to simulate an I/O
    # failure at the very last step -- the cycle must still fail closed.
    ledger.promote = broken_promote  # type: ignore[method-assign]

    report = run_improvement_cycle(
        presentations=[_presentation("patient-1", ["claim-1"])],
        clinician_actions=[],
        target=ImproveTarget.MODEL_A_PROMPT,
        generate=generate,
        score_fn=_improving_score_fn,
        ledger=ledger,
        now=_NOW,
        version="v1",
    )

    assert report.accepted is False
    assert report.promotion is None
    assert report.evaluation is not None
    assert "disk full" in report.detail
