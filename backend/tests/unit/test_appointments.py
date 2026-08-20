"""Tests for `app.tasks.appointments` (spec §48/§28A.2): IST "tomorrow"
resolution and the in-memory appointment lookup."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.tasks.appointments import InMemoryAppointmentSource, tomorrow_ist


def test_tomorrow_ist_past_2330_boundary_rolls_to_day_after_next() -> None:
    # 18:30 UTC = 00:00 IST the next day -> "tomorrow" is two days ahead of
    # the UTC calendar date.
    now_utc = datetime(2026, 8, 20, 18, 30, 0, tzinfo=UTC)
    assert tomorrow_ist(now_utc) == date(2026, 8, 22)


def test_tomorrow_ist_before_2330_boundary() -> None:
    # 17:59 UTC = 23:29 IST same day -> "tomorrow" is one day ahead.
    now_utc = datetime(2026, 8, 20, 17, 59, 0, tzinfo=UTC)
    assert tomorrow_ist(now_utc) == date(2026, 8, 21)


def test_tomorrow_ist_rejects_naive_datetime() -> None:
    naive = datetime(2026, 8, 20, 12, 0, 0)
    with pytest.raises(ValueError, match="tz-aware"):
        tomorrow_ist(naive)


def test_in_memory_appointment_source_returns_patients_for_day() -> None:
    source = InMemoryAppointmentSource(
        {
            date(2026, 8, 21): ["pat-1", "pat-2"],
        }
    )
    assert source.patients_for_day(date(2026, 8, 21)) == ["pat-1", "pat-2"]


def test_in_memory_appointment_source_returns_empty_for_unknown_day() -> None:
    source = InMemoryAppointmentSource({})
    assert source.patients_for_day(date(2026, 8, 21)) == []
