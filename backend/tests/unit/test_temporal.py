"""Unit tests for app.normalize.temporal.

Verifies precision-aware parsing and ordering: coarse (YEAR/MONTH/DAY)
values are compared as intervals in DISPLAY_TZ, never fabricated into a
midnight-UTC point; offset-qualified instants compare correctly across
timezones; naive datetimes can never enter a ClinicalInstant.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.normalize.errors import NormalizationError, TemporalParseError
from app.normalize.temporal import (
    ClinicalInstant,
    Ordering,
    Precision,
    _interval_utc,
    absent_instant,
    compare,
    parse_effective_period,
    parse_fhir_datetime,
)


def test_date_only_has_day_precision_and_spans_full_ist_day() -> None:
    inst = parse_fhir_datetime("2025-03-04")
    assert inst.precision == Precision.DAY

    interval = _interval_utc(inst)
    assert interval is not None
    lo, hi = interval
    assert (hi - lo).total_seconds() == 24 * 3600

    # A naive implementation would treat the date as midnight UTC. Midnight
    # UTC on 2025-03-04 is 05:30 IST, which sits INSIDE this day's IST
    # interval -- so it must not be treated as strictly ordered before/after
    # or as identical (that would require both the same lo AND hi).
    midnight_utc = parse_fhir_datetime("2025-03-04T00:00:00Z")
    assert compare(inst, midnight_utc) == Ordering.INDETERMINATE_ORDER


def test_offset_and_zulu_instants_compare_equal() -> None:
    a = parse_fhir_datetime("2025-03-04T09:15:00+05:30")
    b = parse_fhir_datetime("2025-03-04T03:45:00Z")
    assert compare(a, b) == Ordering.EQUAL
    assert compare(b, a) == Ordering.EQUAL


def test_year_vs_day_is_indeterminate() -> None:
    year = parse_fhir_datetime("2025")
    day = parse_fhir_datetime("2025-06-15")
    assert compare(year, day) == Ordering.INDETERMINATE_ORDER
    assert compare(day, year) == Ordering.INDETERMINATE_ORDER


def test_clearly_before_and_after() -> None:
    earlier = parse_fhir_datetime("2020-01-01")
    later = parse_fhir_datetime("2025-01-01")
    assert compare(earlier, later) == Ordering.BEFORE
    assert compare(later, earlier) == Ordering.AFTER


def test_naive_datetime_rejected() -> None:
    with pytest.raises(NormalizationError):
        ClinicalInstant(
            value_utc=datetime(2025, 1, 1),  # naive
            precision=Precision.SECOND,
            source_string="naive",
            source_offset_present=False,
        )


def test_absent_instant_is_indeterminate_against_anything() -> None:
    absent = absent_instant()
    other = parse_fhir_datetime("2025-01-01T00:00:00Z")
    assert compare(absent, other) == Ordering.INDETERMINATE_ORDER
    assert compare(other, absent) == Ordering.INDETERMINATE_ORDER
    assert compare(absent, absent) == Ordering.INDETERMINATE_ORDER


def test_month_and_year_precisions_parsed() -> None:
    assert parse_fhir_datetime("2025-03").precision == Precision.MONTH
    assert parse_fhir_datetime("2025").precision == Precision.YEAR


def test_millisecond_precision_parsed() -> None:
    inst = parse_fhir_datetime("2025-03-04T09:15:00.123+05:30")
    assert inst.precision == Precision.MILLISECOND
    assert inst.value_utc is not None
    assert inst.value_utc.microsecond == 123000


def test_time_without_offset_raises() -> None:
    with pytest.raises(TemporalParseError):
        parse_fhir_datetime("2025-03-04T09:15:00")


def test_invalid_string_raises() -> None:
    with pytest.raises(TemporalParseError):
        parse_fhir_datetime("not-a-date")


def test_invalid_calendar_value_raises() -> None:
    with pytest.raises(TemporalParseError):
        parse_fhir_datetime("2025-13-04")


def test_parse_effective_period_prefers_start_falls_back_to_end() -> None:
    both = parse_effective_period({"start": "2025-01-01", "end": "2025-02-01"})
    assert both.source_string == "2025-01-01"

    end_only = parse_effective_period({"end": "2025-02-01"})
    assert end_only.source_string == "2025-02-01"

    neither = parse_effective_period({})
    assert neither.precision == Precision.ABSENT
