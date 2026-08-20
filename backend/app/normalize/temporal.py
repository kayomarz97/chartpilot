"""Precision-aware time engine for FHIR date/dateTime/instant values.

FHIR timestamps arrive at wildly different granularities -- a bare year
("2025"), a calendar date with no time-of-day ("2025-03-04"), or a full
offset-qualified instant ("2025-03-04T09:15:00+05:30"). Collapsing all of
these to a single UTC point (e.g. assuming a date-only value means midnight
UTC) silently fabricates precision that was never in the source data and can
misorder clinical events.

This module keeps precision explicit end-to-end:
  - `ClinicalInstant` never claims more precision than the source had, and
    never holds a naive datetime (fail-closed: construction raises rather
    than silently accepting an ambiguous local time).
  - Ordering (`compare`) is interval-based, not point-based: a coarse value
    (YEAR/MONTH/DAY) is compared as the half-open UTC interval its stated
    period covers, in `DISPLAY_TZ` (the documented display timezone, not a
    guess). Two intervals that merely overlap -- rather than being provably
    before/after/exactly-equal -- report `INDETERMINATE_ORDER` instead of a
    fabricated answer.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator

from app.normalize.errors import NormalizationError, TemporalParseError

# The documented clinical display timezone for this deployment. This is a
# display convention (IANA name), not a secret or environment-specific id --
# hard-coding it here is intentional and matches `Settings.display_timezone`.
DISPLAY_TZ = ZoneInfo("Asia/Kolkata")


class Precision(StrEnum):
    """The granularity actually present in the source timestamp string."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    MINUTE = "minute"
    SECOND = "second"
    MILLISECOND = "millisecond"
    ABSENT = "absent"


class Ordering(StrEnum):
    """Result of comparing two `ClinicalInstant` values."""

    BEFORE = "before"
    AFTER = "after"
    EQUAL = "equal"
    INDETERMINATE_ORDER = "indeterminate_order"


class ClinicalInstant(BaseModel):
    """A FHIR timestamp, parsed with its true precision preserved.

    `value_utc` is either `None` (precision ABSENT / no value) or a
    tz-aware UTC datetime. For coarse precisions (YEAR/MONTH/DAY) it holds
    the START of the covered period (in `DISPLAY_TZ`, converted to UTC) --
    it is NOT a claim that the event happened at that instant; see
    `compare` / `_interval_utc` for how coarse values are actually ordered.
    """

    model_config = ConfigDict(frozen=True)

    value_utc: datetime | None
    precision: Precision
    source_string: str | None
    source_offset_present: bool

    @field_validator("value_utc")
    @classmethod
    def _reject_naive(cls, v: datetime | None) -> datetime | None:
        """Fail closed: no naive datetime may ever exist in this model."""
        if v is None:
            return v
        if v.tzinfo is None or v.utcoffset() is None:
            raise NormalizationError(
                "ClinicalInstant.value_utc must be tz-aware or None; got a naive datetime"
            )
        return v.astimezone(UTC)


def absent_instant(source_string: str | None = None) -> ClinicalInstant:
    """Construct the ABSENT instant (no determinable timeline position)."""
    return ClinicalInstant(
        value_utc=None,
        precision=Precision.ABSENT,
        source_string=source_string,
        source_offset_present=False,
    )


# FHIR date/dateTime grammar (simplified, permissive about MINUTE-only time
# even though strict FHIR dateTime always includes seconds once a time is
# present -- we accept it defensively rather than reject data we could
# otherwise place safely on the timeline).
_DATETIME_RE = re.compile(
    r"^(?P<year>\d{4})"
    r"(-(?P<month>\d{2})"
    r"(-(?P<day>\d{2})"
    r"(T(?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(:(?P<second>\d{2})(\.(?P<frac>\d+))?)?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})?"
    r")?"
    r")?"
    r")?$"
)


def _parse_offset(offset: str) -> timezone:
    if offset == "Z":
        return UTC
    sign = 1 if offset[0] == "+" else -1
    hours = int(offset[1:3])
    minutes = int(offset[4:6])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _start_of_period_utc(year: int, month: int, day: int) -> datetime:
    local = datetime(year, month, day, 0, 0, 0, tzinfo=DISPLAY_TZ)
    return local.astimezone(UTC)


def parse_fhir_datetime(raw: str) -> ClinicalInstant:
    """Parse a FHIR `date` / `dateTime` / `instant` string.

    Raises:
        TemporalParseError: `raw` is empty, malformed, has an out-of-range
            calendar component, or has a time-of-day component with no
            UTC offset (FHIR requires an offset whenever a time is given).
    """
    if not raw or not raw.strip():
        raise TemporalParseError("empty FHIR date/dateTime string")

    match = _DATETIME_RE.match(raw.strip())
    if match is None:
        raise TemporalParseError(f"not a valid FHIR date/dateTime string: {raw!r}")

    year = int(match["year"])
    month_s = match["month"]
    day_s = match["day"]
    hour_s = match["hour"]
    minute_s = match["minute"]
    second_s = match["second"]
    frac_s = match["frac"]
    offset_s = match["offset"]

    try:
        if hour_s is not None:
            if offset_s is None:
                raise TemporalParseError(
                    f"FHIR dateTime with a time component requires a UTC offset: {raw!r}"
                )
            assert month_s is not None and day_s is not None
            month, day = int(month_s), int(day_s)
            hour, minute = int(hour_s), int(minute_s)
            tz = _parse_offset(offset_s)

            if second_s is not None:
                second = int(second_s)
                if frac_s is not None:
                    micros = int((frac_s + "000000")[:6])
                    precision = Precision.MILLISECOND
                else:
                    micros = 0
                    precision = Precision.SECOND
            else:
                second = 0
                micros = 0
                precision = Precision.MINUTE

            local_dt = datetime(year, month, day, hour, minute, second, micros, tzinfo=tz)
            value_utc = local_dt.astimezone(UTC)
            return ClinicalInstant(
                value_utc=value_utc,
                precision=precision,
                source_string=raw,
                source_offset_present=True,
            )

        if day_s is not None:
            assert month_s is not None
            value_utc = _start_of_period_utc(year, int(month_s), int(day_s))
            precision = Precision.DAY
        elif month_s is not None:
            value_utc = _start_of_period_utc(year, int(month_s), 1)
            precision = Precision.MONTH
        else:
            value_utc = _start_of_period_utc(year, 1, 1)
            precision = Precision.YEAR

        return ClinicalInstant(
            value_utc=value_utc,
            precision=precision,
            source_string=raw,
            source_offset_present=False,
        )
    except TemporalParseError:
        raise
    except (ValueError, AssertionError) as exc:
        raise TemporalParseError(f"invalid FHIR date/dateTime string {raw!r}: {exc}") from exc


def _interval_utc(inst: ClinicalInstant) -> tuple[datetime, datetime] | None:
    """Return the half-open `[lo, hi)` UTC interval `inst` covers, or None.

    None means "no determinable position on the timeline" (ABSENT / no
    value) -- callers must treat this as indeterminate, never as a fallback
    point in time.
    """
    if inst.precision == Precision.ABSENT or inst.value_utc is None:
        return None

    lo = inst.value_utc

    if inst.precision in (Precision.YEAR, Precision.MONTH, Precision.DAY):
        local_start = lo.astimezone(DISPLAY_TZ)
        if inst.precision == Precision.YEAR:
            next_local = local_start.replace(year=local_start.year + 1)
        elif inst.precision == Precision.MONTH:
            if local_start.month == 12:
                next_local = local_start.replace(year=local_start.year + 1, month=1)
            else:
                next_local = local_start.replace(month=local_start.month + 1)
        else:  # DAY
            next_local = local_start + timedelta(days=1)
        hi = next_local.astimezone(UTC)
        return (lo, hi)

    if inst.precision == Precision.MINUTE:
        return (lo, lo + timedelta(minutes=1))
    if inst.precision == Precision.SECOND:
        return (lo, lo + timedelta(seconds=1))
    if inst.precision == Precision.MILLISECOND:
        return (lo, lo + timedelta(milliseconds=1))
    return None


def compare(a: ClinicalInstant, b: ClinicalInstant) -> Ordering:
    """Compare two instants using their precision-aware UTC intervals.

    Two intervals that overlap without being identical are neither
    provably before, after, nor equal -- they report INDETERMINATE_ORDER
    rather than fabricating an answer the source data doesn't support.
    """
    interval_a = _interval_utc(a)
    interval_b = _interval_utc(b)
    if interval_a is None or interval_b is None:
        return Ordering.INDETERMINATE_ORDER

    a_lo, a_hi = interval_a
    b_lo, b_hi = interval_b

    if a_hi <= b_lo:
        return Ordering.BEFORE
    if b_hi <= a_lo:
        return Ordering.AFTER
    if a_lo == b_lo and a_hi == b_hi:
        return Ordering.EQUAL
    return Ordering.INDETERMINATE_ORDER


def parse_effective_period(period: dict[str, Any]) -> ClinicalInstant:
    """Parse a FHIR `Period` (e.g. `Observation.effectivePeriod`).

    Uses `start`, falling back to `end` if `start` is absent. If neither is
    present, returns an ABSENT instant rather than raising -- a Period with
    no bounds is valid FHIR, just clinically uninformative for ordering.
    """
    start = period.get("start")
    end = period.get("end")
    raw = start if start else end
    if not raw:
        return absent_instant()
    return parse_fhir_datetime(raw)
