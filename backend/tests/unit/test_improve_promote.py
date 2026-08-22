"""Tests for `app.improve.promote.PromotionLedger`/`canary_compare` and
`app.improve.registry.resolve_artifact`.

Every ledger is constructed with pytest's `tmp_path` -- never the real
default directory -- so this suite writes nothing into the repo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.improve.errors import FrozenTargetError
from app.improve.models import ImproveTarget, Metrics
from app.improve.promote import PromotionLedger, canary_compare
from app.improve.registry import resolve_artifact

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)


def test_promote_writes_artifact_and_flips_active(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)

    record = ledger.promote(
        ImproveTarget.MODEL_A_PROMPT,
        "prompt v1 text",
        version="v1",
        rationale="first promotion",
        now=_NOW,
    )

    assert record.active is True
    assert record.version == "v1"
    active = ledger.active(ImproveTarget.MODEL_A_PROMPT)
    assert active is not None
    assert active.version == "v1"


def test_active_value_returns_the_promoted_text(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "prompt v1 text", version="v1", rationale="r", now=_NOW
    )

    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "prompt v1 text"


def test_a_second_promotion_becomes_active_and_supersedes_the_first(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(ImproveTarget.MODEL_A_PROMPT, "v1 text", version="v1", rationale="r", now=_NOW)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "v2 text", version="v2", rationale="r2", now=_LATER
    )

    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "v2 text"
    active = ledger.active(ImproveTarget.MODEL_A_PROMPT)
    assert active is not None
    assert active.version == "v2"


def test_rollback_restores_the_prior_version(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(ImproveTarget.MODEL_A_PROMPT, "v1 text", version="v1", rationale="r", now=_NOW)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "v2 text", version="v2", rationale="r2", now=_LATER
    )

    reverted = ledger.rollback(ImproveTarget.MODEL_A_PROMPT)

    assert reverted is not None
    assert reverted.version == "v1"
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "v1 text"


def test_rollback_on_a_single_promotion_returns_none_and_leaves_active_unchanged(
    tmp_path: Path,
) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(ImproveTarget.MODEL_A_PROMPT, "v1 text", version="v1", rationale="r", now=_NOW)

    reverted = ledger.rollback(ImproveTarget.MODEL_A_PROMPT)

    assert reverted is None
    assert ledger.active_value(ImproveTarget.MODEL_A_PROMPT) == "v1 text"


def test_rollback_on_an_empty_ledger_returns_none(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    assert ledger.rollback(ImproveTarget.MODEL_A_PROMPT) is None


def test_targets_do_not_interfere_with_each_other(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "prompt text", version="v1", rationale="r", now=_NOW
    )

    assert ledger.active_value(ImproveTarget.EVIDENCE_RANKING) is None
    assert ledger.active(ImproveTarget.EVIDENCE_RANKING) is None


def test_promote_refuses_a_frozen_target(tmp_path: Path) -> None:
    ledger = PromotionLedger(tmp_path)
    with pytest.raises(FrozenTargetError):
        ledger.promote(
            "k_high_risk_001",  # type: ignore[arg-type]
            "malicious value",
            version="v1",
            rationale="r",
            now=_NOW,
        )
    # Refused before any write happened.
    assert not any(tmp_path.iterdir())


def test_resolve_artifact_with_no_ledger_returns_the_default() -> None:
    assert resolve_artifact(ImproveTarget.MODEL_A_PROMPT, "pinned default text") == (
        "pinned default text"
    )


def test_resolve_artifact_with_an_empty_ledger_returns_the_default_byte_identical(
    tmp_path: Path,
) -> None:
    ledger = PromotionLedger(tmp_path)
    result = resolve_artifact(ImproveTarget.MODEL_A_PROMPT, "pinned default text", ledger=ledger)
    assert result == "pinned default text"


def test_resolve_artifact_with_an_active_promotion_returns_the_promoted_value(
    tmp_path: Path,
) -> None:
    ledger = PromotionLedger(tmp_path)
    ledger.promote(
        ImproveTarget.MODEL_A_PROMPT, "learned prompt", version="v1", rationale="r", now=_NOW
    )

    result = resolve_artifact(ImproveTarget.MODEL_A_PROMPT, "pinned default text", ledger=ledger)

    assert result == "learned prompt"


def test_canary_compare_true_when_candidate_does_not_regress() -> None:
    def score_fn(value: str) -> Metrics:
        caught = 8 if value == "candidate" else 7
        return Metrics(
            set_d_blocked=7, set_m_caught=caught, false_reject=0, clinician_agreement=1.0
        )

    assert canary_compare("candidate", "active", score_fn=score_fn) is True


def test_canary_compare_false_when_candidate_regresses() -> None:
    def score_fn(value: str) -> Metrics:
        false_reject = 3 if value == "candidate" else 0
        return Metrics(
            set_d_blocked=7, set_m_caught=8, false_reject=false_reject, clinician_agreement=1.0
        )

    assert canary_compare("candidate", "active", score_fn=score_fn) is False
