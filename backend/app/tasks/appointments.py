"""Nightly appointment lookup for fan-out (spec §48, §28A.2).

`tomorrow_ist` answers "which calendar date, in the clinic's display
timezone, is 'tomorrow' relative to now?" -- the nightly run enqueues one
task per patient with an appointment on that date. `AppointmentSource` is
the Protocol a real scheduling-system adapter will implement in a later
phase; `InMemoryAppointmentSource` is the hermetic fake used here and in
tests.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable

from app.normalize.temporal import DISPLAY_TZ

__all__ = ["tomorrow_ist", "AppointmentSource", "InMemoryAppointmentSource"]


def tomorrow_ist(now_utc: datetime) -> date:
    """Return tomorrow's calendar date in `DISPLAY_TZ` (Asia/Kolkata).

    `now_utc` must be tz-aware. Converts to IST, then adds one calendar day
    -- so e.g. 2026-08-20T18:30:00Z (2026-08-21 00:00 IST) yields
    2026-08-22, while 2026-08-20T17:59:00Z (2026-08-20 23:29 IST) yields
    2026-08-21.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("tomorrow_ist requires a tz-aware now_utc; got a naive datetime")
    local_today = now_utc.astimezone(DISPLAY_TZ)
    return (local_today + timedelta(days=1)).date()


@runtime_checkable
class AppointmentSource(Protocol):
    """Anything that can list patient ids with an appointment on `day`."""

    def patients_for_day(self, day: date) -> list[str]:
        """Return the patient ids with an appointment on `day`."""
        ...


class InMemoryAppointmentSource:
    """Hermetic in-memory `AppointmentSource`, built from a fixed calendar."""

    def __init__(self, appointments_by_day: dict[date, list[str]]) -> None:
        self._appointments_by_day = dict(appointments_by_day)

    def patients_for_day(self, day: date) -> list[str]:
        return list(self._appointments_by_day.get(day, []))
