"""Tests for `app.feedback.models.ClinicianAction` (Phase B, spec §53)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.feedback.models import ClinicianAction, ClinicianActionKind


def _kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action_id": "patient-1:claim-1",
        "run_id": "run-1",
        "patient_id": "patient-1",
        "claim_id": "claim-1",
        "action": ClinicianActionKind.CONFIRM,
        "recorded_at": datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return payload


def test_naive_recorded_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClinicianAction(**_kwargs(recorded_at=datetime(2026, 8, 20, 12, 0, 0)))


def test_tz_aware_recorded_at_is_accepted_and_normalized_to_utc() -> None:
    action = ClinicianAction(**_kwargs())
    assert action.recorded_at.tzinfo is not None


def test_note_defaults_to_empty_and_trusted_is_always_false() -> None:
    action = ClinicianAction(**_kwargs())
    assert action.note == ""
    assert action.trusted is False


def test_trusted_cannot_be_overridden_to_true() -> None:
    """`trusted: Literal[False] = False` -- pydantic rejects any other
    literal value passed in, closing off the one obvious way someone could
    try to smuggle a "trusted" clinician note past spec §53."""
    with pytest.raises(ValidationError):
        ClinicianAction(**_kwargs(trusted=True))


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        ClinicianAction(**_kwargs(unexpected_field="nope"))


@pytest.mark.parametrize("kind", list(ClinicianActionKind))
def test_all_three_action_kinds_are_constructible(kind: ClinicianActionKind) -> None:
    action = ClinicianAction(**_kwargs(action=kind))
    assert action.action == kind
